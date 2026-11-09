# ---------------------------------------------------------------------------
# Lab-2 event pipeline: queues, table, Event Grid, ACS Email
# ---------------------------------------------------------------------------

locals {
  queue_names = {
    ingress         = "q-ingress"
    extract_invoice = "q-extract-invoice"
    extract_read    = "q-extract-read"
    extract_unknown = "q-extract-unknown"
    delete_pdf      = "q-delete-pdf"
    delete_result   = "q-delete-result"
    notify          = "q-notify"
  }
}

resource "azurerm_storage_queue" "ingress" {
  name                 = local.queue_names.ingress
  storage_account_name = azurerm_storage_account.docs.name
  depends_on           = [time_sleep.storage_ready]
}

resource "azurerm_storage_queue" "extract_invoice" {
  name                 = local.queue_names.extract_invoice
  storage_account_name = azurerm_storage_account.docs.name
  depends_on           = [time_sleep.storage_ready]
}

resource "azurerm_storage_queue" "extract_read" {
  name                 = local.queue_names.extract_read
  storage_account_name = azurerm_storage_account.docs.name
  depends_on           = [time_sleep.storage_ready]
}

resource "azurerm_storage_queue" "extract_unknown" {
  name                 = local.queue_names.extract_unknown
  storage_account_name = azurerm_storage_account.docs.name
  depends_on           = [time_sleep.storage_ready]
}

resource "azurerm_storage_queue" "delete_pdf" {
  name                 = local.queue_names.delete_pdf
  storage_account_name = azurerm_storage_account.docs.name
  depends_on           = [time_sleep.storage_ready]
}

resource "azurerm_storage_queue" "delete_result" {
  name                 = local.queue_names.delete_result
  storage_account_name = azurerm_storage_account.docs.name
  depends_on           = [time_sleep.storage_ready]
}

resource "azurerm_storage_queue" "notify" {
  name                 = local.queue_names.notify
  storage_account_name = azurerm_storage_account.docs.name
  depends_on           = [time_sleep.storage_ready]
}

resource "azurerm_storage_table" "doc_hashes" {
  name                 = "docHashes"
  storage_account_name = azurerm_storage_account.docs.name
  depends_on           = [time_sleep.storage_ready]
}

# Training set for Document Intelligence custom classifier (folder-per-class)
resource "azurerm_storage_container" "classifier_train" {
  name                  = "classifier-train"
  storage_account_id    = azurerm_storage_account.docs.id
  container_access_type = "private"

  depends_on = [time_sleep.storage_ready]
}

resource "azurerm_eventgrid_system_topic" "storage" {
  name                   = "${var.prefix}-eg-storage-${random_string.suffix.result}"
  resource_group_name    = azurerm_resource_group.lab1.name
  location               = azurerm_resource_group.lab1.location
  source_arm_resource_id = azurerm_storage_account.docs.id
  topic_type             = "Microsoft.Storage.StorageAccounts"

  tags = azurerm_resource_group.lab1.tags
}

resource "azurerm_eventgrid_system_topic_event_subscription" "blob_created_ingress" {
  name                = "sub-blob-created-ingress"
  system_topic        = azurerm_eventgrid_system_topic.storage.name
  resource_group_name = azurerm_resource_group.lab1.name

  included_event_types = ["Microsoft.Storage.BlobCreated"]

  subject_filter {
    subject_begins_with = "/blobServices/default/containers/${azurerm_storage_container.invoices_in.name}/blobs/"
    subject_ends_with   = ".pdf"
  }

  storage_queue_endpoint {
    storage_account_id                    = azurerm_storage_account.docs.id
    queue_name                            = azurerm_storage_queue.ingress.name
    queue_message_time_to_live_in_seconds = 604800
  }

  retry_policy {
    max_delivery_attempts = 10
    event_time_to_live    = 1440
  }

  depends_on = [azurerm_storage_queue.ingress]
}

resource "azurerm_eventgrid_system_topic_event_subscription" "blob_deleted_result" {
  name                = "sub-blob-deleted-result"
  system_topic        = azurerm_eventgrid_system_topic.storage.name
  resource_group_name = azurerm_resource_group.lab1.name

  included_event_types = ["Microsoft.Storage.BlobDeleted"]

  advanced_filter {
    string_begins_with {
      key = "subject"
      values = [
        "/blobServices/default/containers/${azurerm_storage_container.invoices_out_invoice.name}/blobs/",
        "/blobServices/default/containers/${azurerm_storage_container.invoices_out_read.name}/blobs/",
      ]
    }
  }

  storage_queue_endpoint {
    storage_account_id                    = azurerm_storage_account.docs.id
    queue_name                            = azurerm_storage_queue.delete_result.name
    queue_message_time_to_live_in_seconds = 604800
  }

  retry_policy {
    max_delivery_attempts = 10
    event_time_to_live    = 1440
  }

  depends_on = [azurerm_storage_queue.delete_result]
}

resource "azurerm_communication_service" "notify" {
  name                = substr("${var.prefix}-acs-${random_string.suffix.result}", 0, 63)
  resource_group_name = azurerm_resource_group.lab1.name
  data_location       = var.acs_data_location

  tags = azurerm_resource_group.lab1.tags
}

resource "azurerm_email_communication_service" "notify" {
  name                = substr("${var.prefix}-email-${random_string.suffix.result}", 0, 63)
  resource_group_name = azurerm_resource_group.lab1.name
  data_location       = var.acs_data_location

  tags = azurerm_resource_group.lab1.tags
}

resource "azurerm_email_communication_service_domain" "azure_managed" {
  name              = "AzureManagedDomain"
  email_service_id  = azurerm_email_communication_service.notify.id
  domain_management = "AzureManaged"
}

resource "azurerm_communication_service_email_domain_association" "notify" {
  communication_service_id = azurerm_communication_service.notify.id
  email_service_domain_id  = azurerm_email_communication_service_domain.azure_managed.id
}
