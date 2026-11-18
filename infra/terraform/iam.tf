data "aws_iam_policy_document" "api" {
  statement {
    actions   = ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.documents.arn}/*"]
  }

  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.documents.arn]
  }

  statement {
    actions   = ["ses:SendEmail"]
    resources = [aws_ses_email_identity.sender.arn]
  }
}

resource "aws_iam_policy" "api" {
  name   = "projects-api-documents"
  policy = data.aws_iam_policy_document.api.json
}
