# On real AWS the address must confirm a verification email before SES sends from it
resource "aws_ses_email_identity" "sender" {
  email = var.sender_email
}
