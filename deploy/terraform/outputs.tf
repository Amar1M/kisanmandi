# Outputs. These are what you paste into your notes, your README and your report.

output "instance_id" {
  description = "OCID of the application VM"
  value       = oci_core_instance.app.id
}

output "public_ip" {
  description = "Public IP address — use this for SSH"
  value       = oci_core_instance.app.public_ip
}

output "ssh_command" {
  description = "Ready-to-run SSH command"
  value       = "ssh ubuntu@${oci_core_instance.app.public_ip}"
}

output "region" {
  description = "Region the VM landed in"
  value       = var.region
}

output "instance_shape_summary" {
  description = "What you actually got, for your report"
  value       = "${var.instance_shape}: ${var.instance_ocpus} OCPU / ${var.instance_memory_gb} GB RAM / ${var.boot_volume_gb} GB boot"
}

output "always_free_monthly_cost" {
  description = "Reminder of what this costs"
  value       = "INR 0.00 — Always Free resources, no expiry"
}

output "next_steps" {
  description = "What to do after apply finishes"
  value       = <<-EOT

    1. Wait ~2 minutes for cloud-init to finish, then connect:
         ssh ubuntu@${oci_core_instance.app.public_ip}

    2. Verify the baseline install (it takes about a minute after boot):
         cloud-init status --wait
         docker --version
         sudo ufw status

    3. Get a free data.gov.in API key:
         https://data.gov.in/user/register

    4. Clone the project and configure it:
         git clone https://github.com/Amar1M/kisanmandi.git
         cd kisanmandi && cp .env.example .env && nano .env   # add your API key
         chmod 600 .env

    5. First real run:
         python3 -m venv .venv && source .venv/bin/activate
         pip install -e .
         kisanmandi stats
         kisanmandi ingest --state Karnataka

    6. Then install the systemd timer:
         sudo cp deploy/systemd/kisanmandi-* /etc/systemd/system/
         sudo systemctl daemon-reload
         sudo systemctl enable --now kisanmandi-ingest.timer

    7. PROVE IT COSTS NOTHING:
         OCI console -> Billing & Cost Management -> Cost Analysis
         It should read INR 0.00. Screenshot it for your report.
  EOT
}
