# Static external IP for the VM (used by your CI as TF_ADDRESS_NAME)
resource "google_compute_address" "ip" {
  name         = var.tf_address_name   # e.g. "yt-llm-k3s-ip"
  region       = var.region
  address_type = "EXTERNAL"
}

# Firewall rule: SSH, HTTP, HTTPS, NodePort 30080 (if needed)
resource "google_compute_firewall" "allow_web_ssh" {
  name    = "${var.vm_name}-allow-web-ssh"
  network = "default"

  allow {
    protocol = "tcp"
    ports    = ["22", "80", "443", "30080"]
  }

  # Allow anyone on the internet to connect on these ports
  source_ranges = ["0.0.0.0/0"]

  # Target instances tagged with this tag
  target_tags = [var.instance_tag]

  description = "Allow SSH, HTTP, HTTPS, and NodePort 30080 to ${var.vm_name}"
}

# The k3s VM
resource "google_compute_instance" "k3s_vm" {
  name         = var.vm_name              # e.g. "yt-llm-k3s"
  machine_type = var.machine_type         # e.g. "e2-medium" (2 vCPU, 4GB)
  zone         = var.zone
  project      = var.project_id

  tags = [var.instance_tag]

  boot_disk {
    initialize_params {
      image = var.boot_image              # e.g. "debian-cloud/debian-12"
      size  = var.disk_size_gb            # e.g. 30
      type  = "pd-balanced"
    }
  }

  network_interface {
    network = "default"

    access_config {
      # Reuse existing static IP managed as google_compute_address.ip
      nat_ip = google_compute_address.ip.address
    }
  }

  # Enable OS Login (recommended)
  metadata = {
    enable-oslogin = "TRUE"
  }

  service_account {
    email  = var.service_account_email
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }
}
