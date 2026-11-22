#!/bin/sh
# Creates the local bucket with versioning, mirroring the AWS configuration.
awslocal s3api create-bucket --bucket onward-local-photos --create-bucket-configuration LocationConstraint=eu-west-1
awslocal s3api put-bucket-versioning --bucket onward-local-photos --versioning-configuration Status=Enabled
