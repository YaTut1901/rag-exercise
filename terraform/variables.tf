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

variable "postgres_admin_login" {
  description = "PostgreSQL Flexible Server admin login"
  type        = string
  default     = "ragadmin"
}

variable "postgres_database_name" {
  description = "Database name for invoice rows"
  type        = string
  default     = "invoices"
}

variable "postgres_version" {
  description = "PostgreSQL major version"
  type        = string
  default     = "16"
}

variable "postgres_sku_name" {
  description = "Flexible Server SKU (Burstable B1ms is cheapest for labs)"
  type        = string
  default     = "B_Standard_B1ms"
}

variable "postgres_storage_mb" {
  description = "Flexible Server storage in MB"
  type        = number
  default     = 32768
}

variable "postgres_zone" {
  description = "Availability zone for Flexible Server (region-dependent)"
  type        = string
  default     = "1"
}

variable "openai_location" {
  description = "Region for Azure OpenAI (often differs from main RG location)"
  type        = string
  default     = "swedencentral"
}

variable "openai_embedding_deployment_name" {
  description = "Deployment name used as model= in embeddings API calls"
  type        = string
  default     = "text-embedding-3-small"
}

variable "openai_embedding_model_name" {
  description = "Azure OpenAI embedding model name"
  type        = string
  default     = "text-embedding-3-small"
}

variable "openai_embedding_model_version" {
  description = "Embedding model version"
  type        = string
  default     = "1"
}

variable "openai_embedding_sku" {
  description = "Embeddings deployment SKU (GlobalStandard required for text-embedding-3-small in many EU regions)"
  type        = string
  default     = "GlobalStandard"
}

variable "openai_embedding_capacity" {
  description = "Embeddings deployment TPM capacity (thousands)"
  type        = number
  default     = 10
}

variable "openai_embedding_dimensions" {
  description = "Embedding vector size written to doc_chunks.embedding"
  type        = number
  default     = 1536
}

variable "openai_chat_deployment_name" {
  description = "Deployment name used as model= in chat API calls"
  type        = string
  default     = "gpt-4.1-mini"
}

variable "openai_chat_model_name" {
  description = "Azure OpenAI chat model name"
  type        = string
  default     = "gpt-4.1-mini"
}

variable "openai_chat_model_version" {
  description = "Chat model version"
  type        = string
  default     = "2025-04-14"
}

variable "openai_chat_sku" {
  description = "Chat deployment SKU"
  type        = string
  default     = "GlobalStandard"
}

variable "openai_chat_capacity" {
  description = "Chat deployment TPM capacity (thousands)"
  type        = number
  default     = 10
}

variable "ui_sku_name" {
  description = "App Service plan SKU for Streamlit UI (B3: more RAM for Streamlit+plotly)"
  type        = string
  default     = "B3"
}
