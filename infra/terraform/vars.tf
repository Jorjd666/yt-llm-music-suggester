variable "project_id" {
  description = "GCP project ID"
  type        = string
  default     = "splendid-window-478312-m6"
}

# Frankfurt is a good EU choice (close to RO)
variable "region" {
  description = "GCP region"
  type        = string
  default     = "europe-west3"
}

variable "zone" {
  description = "GCP zone"
  type        = string
  default     = "europe-west3-c"
}

variable "ssh_pub_key_path" {
  description = "Path to your SSH public key"
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}


variable "tf_address_name" {
  description = "Name for the static external IP (TF_ADDRESS_NAME in CI)"
  type        = string
  default     = "yt-llm-k3s-ip"
}

variable "vm_name" {
  description = "Name of the k3s VM"
  type        = string
  default     = "yt-llm-k3s"
}

variable "machine_type" {
  description = "GCE machine type"
  type        = string
  # e2-medium = 2 vCPU, 4 GB RAM (good starting point)
  default     = "e2-medium"
}

variable "disk_size_gb" {
  description = "Boot disk size (GB)"
  type        = number
  default     = 30
}

variable "boot_image" {
  description = "Boot image for the VM"
  type        = string
  # Debian 12 is a solid base for k3s + Ansible
  default     = "debian-cloud/debian-12"
}

variable "instance_tag" {
  description = "Network tag for firewall targeting"
  type        = string
  default     = "yt-llm-k3s-tag"
}

variable "service_account_email" {
  description = "Service account email for the VM (or default if empty)"
  type        = string
  default     = ""
}

