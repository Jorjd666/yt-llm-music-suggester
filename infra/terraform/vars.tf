variable "project_id" {}
variable "region" { default = "us-central1" }
variable "zone" { default = "us-central1-a" }
variable "instance_name" { default = "yt-llm-k3s" }
variable "ssh_pub_key_path" { default = "~/.ssh/id_rsa.pub" }
variable "machine_type" { default = "e2-small" }  # or "e2-medium"
