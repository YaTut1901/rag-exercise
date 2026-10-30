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
