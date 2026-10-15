# Input variables. Everything you must supply lives here so nothing is hard-coded.

variable "project_name" {
  description = "Prefix for every resource name"
  type        = string
  default     = "kisanmandi"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,30}$", var.project_name))
    error_message = "Use lowercase letters, numbers and hyphens only (3-31 chars)."
  }
}

# --- OCI credentials -------------------------------------------------------
# Get these from the OCI console:
#   Profile menu -> My profile -> API keys -> Add API key
# It gives you a config file preview containing most of these values.

variable "tenancy_ocid" {
  description = "OCID of your tenancy"
  type        = string
  sensitive   = true
}

variable "user_ocid" {
  description = "OCID of your user"
  type        = string
  sensitive   = true
}

variable "fingerprint" {
  description = "Fingerprint of the API signing key"
  type        = string
}

variable "private_key_path" {
  description = "Local path to your OCI API private key (e.g. ~/.oci/oci_api_key.pem)"
  type        = string
}

variable "compartment_ocid" {
  description = "Compartment to create resources in. Use tenancy_ocid for the root compartment."
  type        = string
}

variable "region" {
  description = "OCI region. If ARM capacity is unavailable, try another (e.g. ap-singapore-1, eu-frankfurt-1)."
  type        = string
  default     = "ap-mumbai-1"
}

# --- VM shape (Always Free limits) -----------------------------------------
# The Always Free allowance is 4 OCPUs and 24 GB RAM *total*, across all A1 VMs.
# Exceeding it starts billing, so these are capped below.

variable "instance_shape" {
  description = "Ampere A1 shape. Do not change — GPU shapes are not free."
  type        = string
  default     = "VM.Standard.A1.Flex"
}

variable "instance_ocpus" {
  description = "ARM OCPUs. Always Free maximum is 4."
  type        = number
  default     = 4

  validation {
    condition     = var.instance_ocpus > 0 && var.instance_ocpus <= 4
    error_message = "Always Free allows 1-4 OCPUs. More than 4 will be billed."
  }
}

variable "instance_memory_gb" {
  description = "RAM in GB. Always Free maximum is 24."
  type        = number
  default     = 24

  validation {
    condition     = var.instance_memory_gb > 0 && var.instance_memory_gb <= 24
    error_message = "Always Free allows 1-24 GB RAM. More than 24 will be billed."
  }
}

variable "boot_volume_gb" {
  description = "Boot volume size. Always Free allows 200 GB total block storage."
  type        = number
  default     = 100

  validation {
    condition     = var.boot_volume_gb >= 47 && var.boot_volume_gb <= 200
    error_message = "Must be 47-200 GB. Oracle requires at least 47 GB for a custom boot volume."
  }
}

variable "availability_domain_index" {
  description = "Which availability domain to use (0, 1 or 2). If one is out of capacity, try another."
  type        = number
  default     = 0
}

# --- Access -----------------------------------------------------------------

variable "ssh_public_key_path" {
  description = "Path to your SSH *public* key. Ansible uses these keys too."
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "admin_cidr" {
  description = "CIDR allowed to SSH. Set this to your own IP, not 0.0.0.0/0."
  type        = string
  default     = "0.0.0.0/0" # permissive default for throwaway setups — narrow it

  validation {
    condition     = can(cidrhost(var.admin_cidr, 0))
    error_message = "Must be a valid CIDR block, e.g. 203.0.113.42/32 or 10.0.0.0/16."
  }
}

variable "timezone" {
  description = "VM timezone. Cron schedules in the app assume UTC unless you change this."
  type        = string
  default     = "Asia/Kolkata"
}
