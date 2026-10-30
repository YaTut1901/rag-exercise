variable "subscription_id" {
  description = "Azure subscription ID"
  type        = string
}

variable "location" {
  description = "Azure region"
  type        = string
  default     = "switzerlandnorth"
}

variable "prefix" {
  description = "Short unique prefix for resource names (lowercase alphanumeric)"
  type        = string
  default     = "raglab1"
}

variable "resource_group_name" {
  description = "Resource group name"
  type        = string
  default     = "rg-rag-lab1"
}

variable "blob_soft_delete_days" {
  description = "Soft-delete retention for blobs (needed by delete-result hash lookup)"
  type        = number
  default     = 7
}

variable "classifier_model_id" {
  description = "Document Intelligence custom classifier model id (empty until trained)"
  type        = string
  default     = ""
}

variable "classify_min_confidence" {
  description = "Minimum classifier confidence to accept invoice/other (else extract-unknown)"
  type        = number
  default     = 0.6
}

variable "queue_max_dequeue_count" {
  description = "Retries before poison; extract notifies on last attempt"
  type        = number
  default     = 5
}

variable "acs_data_location" {
  description = "ACS / Email data location (United States, Europe, …)"
  type        = string
  default     = "Europe"
}
