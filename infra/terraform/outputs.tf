# If you want to keep the "static_ip" output name:
output "static_ip" {
  description = "Static external IP address for the k3s VM"
  value       = google_compute_address.ip.address
}

# Optional: keep vm_name output
output "vm_name" {
  description = "Name of the k3s VM"
  value       = google_compute_instance.k3s_vm.name
}
