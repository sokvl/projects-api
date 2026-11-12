variable "region" {
  type    = string
  default = "eu-central-1"
}

variable "bucket_name" {
  type        = string
  description = "Globally unique on real AWS"
  default     = "documents"
}

variable "use_emulator" {
  type    = bool
  default = false
}
