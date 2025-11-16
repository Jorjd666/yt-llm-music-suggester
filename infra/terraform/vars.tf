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

variable "instance_name" {
  description = "Name for the VM"
  type        = string
  default     = "yt-llm-k3s"
}

variable "ssh_pub_key_path" {
  description = "Path to your SSH public key"
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "machine_type" {
  description = "GCE machine type"
  type        = string
  default     = "e2-small"
}
