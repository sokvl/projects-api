terraform {
  required_version = "~> 1.17"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.72"
    }
  }

  backend "local" {}
}

provider "aws" {
  region = var.region

  skip_credentials_validation = var.use_emulator
  skip_requesting_account_id  = var.use_emulator
  skip_metadata_api_check     = var.use_emulator
  s3_use_path_style           = var.use_emulator
}
