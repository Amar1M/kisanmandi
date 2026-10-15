# KisanMandi infrastructure — Oracle Cloud Always Free
#
# Creates a permanently free VM with 4 ARM cores, 24 GB RAM and 200 GB storage.
# Read ../../docs/02-oracle-setup.md first; this automates that document.
#
# Usage:
#   cd deploy/terraform
#   cp terraform.tfvars.example terraform.tfvars   # then fill it in
#   terraform init
#   terraform plan                                  # read this before applying
#   terraform apply
#
# Cost: ₹0. VM.Standard.A1.Flex within the Always Free limits is not billed.

terraform {
  required_version = ">= 1.5"

  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "~> 6.0"
    }
  }

  # For a student project, local state is honest and fine. Say so in your report.
  # If you enable remote state later, note that the bucket itself may cost money —
  # which is exactly why this project keeps state local.
  backend "local" {
    path = "terraform.tfstate"
  }
}

provider "oci" {
  tenancy_ocid     = var.tenancy_ocid
  user_ocid        = var.user_ocid
  fingerprint      = var.fingerprint
  private_key_path = var.private_key_path
  region           = var.region
}

# ---------------------------------------------------------------------------
# Where to put it
# ---------------------------------------------------------------------------
data "oci_identity_availability_domains" "ads" {
  compartment_id = var.tenancy_ocid
}

# Ubuntu 24.04 for ARM (aarch64). The shape below is Ampere, so the image
# *must* be aarch64 — an x86 image will be rejected.
data "oci_core_images" "ubuntu_arm" {
  compartment_id           = var.compartment_ocid
  operating_system         = "Canonical Ubuntu"
  operating_system_version = "24.04"
  shape                    = var.instance_shape
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"

  filter {
    name   = "display_name"
    values = ["^Canonical-Ubuntu-24\\.04-aarch64-.*"]
    regex  = true
  }
}

# ---------------------------------------------------------------------------
# Network
#
# Deliberately one flat public subnet with a tight security list. No NAT Gateway,
# no bastion, no load balancer -- each of those is a surprise line on a bill, and
# a NAT Gateway alone is roughly ₹3,100/month, which would be more than the
# entire project budget.
# ---------------------------------------------------------------------------
resource "oci_core_vcn" "main" {
  compartment_id = var.compartment_ocid
  cidr_blocks    = ["10.0.0.0/16"]
  display_name   = "${var.project_name}-vcn"
  dns_label      = "kisanmandi"

  freeform_tags = local.common_tags
}

resource "oci_core_internet_gateway" "main" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.main.id
  display_name   = "${var.project_name}-igw"
  enabled        = true

  freeform_tags = local.common_tags
}

resource "oci_core_route_table" "main" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.main.id
  display_name   = "${var.project_name}-rt"

  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.main.id
  }

  freeform_tags = local.common_tags
}

resource "oci_core_security_list" "main" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.main.id
  display_name   = "${var.project_name}-sl"

  # --- SSH, restricted to you ---
  # If var.admin_cidr is 0.0.0.0/0 you will be brute-forced within hours.
  # fail2ban is configured by cloud-init as a second layer, but restricting
  # the source is the first and better one.
  ingress_security_rules {
    description = "SSH from admin CIDR only"
    protocol    = "6" # TCP
    source      = var.admin_cidr
    stateless   = false

    tcp_options {
      min = 22
      max = 22
    }
  }

  # --- HTTP/HTTPS for the API and Grafana once you add ingress ---
  ingress_security_rules {
    description = "HTTP"
    protocol    = "6"
    source      = "0.0.0.0/0"
    stateless   = false

    tcp_options {
      min = 80
      max = 80
    }
  }

  ingress_security_rules {
    description = "HTTPS"
    protocol    = "6"
    source      = "0.0.0.0/0"
    stateless   = false

    tcp_options {
      min = 443
      max = 443
    }
  }

  # --- Outbound: needed to reach data.gov.in ---
  egress_security_rules {
    description = "All outbound"
    protocol    = "all"
    destination = "0.0.0.0/0"
    stateless   = false
  }

  # NOTE: port 5432 (Postgres) is intentionally absent. A database must never be
  # reachable from the internet. The API talks to it over localhost.

  freeform_tags = local.common_tags
}

resource "oci_core_subnet" "main" {
  compartment_id             = var.compartment_ocid
  vcn_id                     = oci_core_vcn.main.id
  cidr_block                 = "10.0.1.0/24"
  display_name               = "${var.project_name}-subnet"
  dns_label                  = "app"
  route_table_id             = oci_core_route_table.main.id
  security_list_ids          = [oci_core_security_list.main.id]
  prohibit_public_ip_on_vnic = false

  freeform_tags = local.common_tags
}

# ---------------------------------------------------------------------------
# The VM
# ---------------------------------------------------------------------------
resource "oci_core_instance" "app" {
  compartment_id      = var.compartment_ocid
  availability_domain = data.oci_identity_availability_domains.ads.availability_domains[var.availability_domain_index].name
  display_name        = "${var.project_name}-app"
  shape               = var.instance_shape

  shape_config {
    ocpus         = var.instance_ocpus
    memory_in_gbs = var.instance_memory_gb
  }

  source_details {
    source_type             = "image"
    source_id               = data.oci_core_images.ubuntu_arm.images[0].id
    boot_volume_size_in_gbs = var.boot_volume_gb
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.main.id
    display_name     = "${var.project_name}-vnic"
    assign_public_ip = true
    hostname_label   = var.project_name
  }

  metadata = {
    ssh_authorized_keys = file(var.ssh_public_key_path)
    user_data = base64encode(templatefile("${path.module}/cloud-init.yaml.tftpl", {
      project_name = var.project_name
      timezone     = var.timezone
    }))
  }

  # Replace the boot volume rather than trying to patch it in place.
  lifecycle {
    ignore_changes = [source_details[0].source_id]
  }

  freeform_tags = local.common_tags
}

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------
locals {
  common_tags = {
    project     = var.project_name
    managed_by  = "terraform"
    environment = "production"
    cost_centre = "zero-rupee-budget"
  }
}
