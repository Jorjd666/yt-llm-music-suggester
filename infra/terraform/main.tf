resource "google_compute_address" "ip" {
  name   = "${var.instance_name}-ip"
  region = var.region
}

resource "google_compute_firewall" "allow_http_https_ssh" {
  name    = "allow-http-https-ssh"
  network = "default"

  allow {
    protocol = "tcp"
    ports    = ["22", "80", "443"]
  }

  source_ranges = ["0.0.0.0/0"]
}

resource "google_compute_instance" "vm" {
  name         = var.instance_name
  machine_type = var.machine_type
  zone         = var.zone

  allow_stopping_for_update = true

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
    }
  }

  network_interface {
    network = "default"
    access_config {
      nat_ip = google_compute_address.ip.address
    }
  }

  metadata = {
    ssh-keys = "debian:${file(pathexpand(var.ssh_pub_key_path))}"
  }

  tags = ["http-server", "https-server"]

  labels = {
    app = var.instance_name
    env = "dev"
  }
}

output "external_ip" {
  description = "Static external IP for the k3s node"
  value       = google_compute_address.ip.address
}
