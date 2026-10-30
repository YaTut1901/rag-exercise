locals {
  storage_name = substr(replace("${var.prefix}st${random_string.suffix.result}", "-", ""), 0, 24)
  func_name    = substr("${var.prefix}-func-${random_string.suffix.result}", 0, 60)
  di_name      = substr("${var.prefix}-di-${random_string.suffix.result}", 0, 60)
}

resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
}

resource "azurerm_resource_group" "lab1" {
  name     = var.resource_group_name
  location = var.location

  tags = {
    project = "rag-lab1"
    course  = "rag-architecture"
  }
}

# ---------------------------------------------------------------------------
# Single storage account: Function runtime + PDF/JSON blobs
# ---------------------------------------------------------------------------
resource "azurerm_storage_account" "docs" {
  name                     = local.storage_name
  resource_group_name      = azurerm_resource_group.lab1.name
  location                 = azurerm_resource_group.lab1.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  min_tls_version          = "TLS1_2"

  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = true

  tags = azurerm_resource_group.lab1.tags
}

resource "time_sleep" "storage_ready" {
  depends_on      = [azurerm_storage_account.docs]
  create_duration = "60s"
}

resource "azurerm_storage_container" "invoices_in" {
  name                  = "invoices-in"
  storage_account_id    = azurerm_storage_account.docs.id
  container_access_type = "private"

  depends_on = [time_sleep.storage_ready]
}

resource "azurerm_storage_container" "invoices_out_read" {
  name                  = "invoices-out-read"
  storage_account_id    = azurerm_storage_account.docs.id
  container_access_type = "private"

  depends_on = [time_sleep.storage_ready]
}

resource "azurerm_storage_container" "invoices_out_invoice" {
  name                  = "invoices-out-invoice"
  storage_account_id    = azurerm_storage_account.docs.id
  container_access_type = "private"

  depends_on = [time_sleep.storage_ready]
}

# ---------------------------------------------------------------------------
# Azure AI Document Intelligence (Free F0 — student-friendly)
# ---------------------------------------------------------------------------
resource "azurerm_cognitive_account" "document_intelligence" {
  name                  = local.di_name
  location              = azurerm_resource_group.lab1.location
  resource_group_name   = azurerm_resource_group.lab1.name
  kind                  = "FormRecognizer"
  sku_name              = "F0"
  custom_subdomain_name = local.di_name

  identity {
    type = "SystemAssigned"
  }

  tags = azurerm_resource_group.lab1.tags
}

# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------
resource "azurerm_log_analytics_workspace" "lab1" {
  name                = "${var.prefix}-law-${random_string.suffix.result}"
  location            = azurerm_resource_group.lab1.location
  resource_group_name = azurerm_resource_group.lab1.name
  sku                 = "PerGB2018"
  retention_in_days   = 30

  tags = azurerm_resource_group.lab1.tags
}

resource "azurerm_application_insights" "lab1" {
  name                = "${var.prefix}-ai-${random_string.suffix.result}"
  location            = azurerm_resource_group.lab1.location
  resource_group_name = azurerm_resource_group.lab1.name
  application_type    = "web"
  workspace_id        = azurerm_log_analytics_workspace.lab1.id

  tags = azurerm_resource_group.lab1.tags
}

# ---------------------------------------------------------------------------
# Function App (Linux Consumption Y1, Python 3.11)
# ---------------------------------------------------------------------------
resource "azurerm_service_plan" "func" {
  name                = "${var.prefix}-plan-${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.lab1.name
  location            = azurerm_resource_group.lab1.location
  os_type             = "Linux"
  sku_name            = "Y1"

  tags = azurerm_resource_group.lab1.tags
}

resource "azurerm_linux_function_app" "ocr" {
  name                = local.func_name
  resource_group_name = azurerm_resource_group.lab1.name
  location            = azurerm_resource_group.lab1.location
  service_plan_id     = azurerm_service_plan.func.id

  storage_account_name       = azurerm_storage_account.docs.name
  storage_account_access_key = azurerm_storage_account.docs.primary_access_key

  identity {
    type = "SystemAssigned"
  }

  site_config {
    application_stack {
      python_version = "3.11"
    }
    application_insights_connection_string = azurerm_application_insights.lab1.connection_string
    application_insights_key               = azurerm_application_insights.lab1.instrumentation_key
  }

  app_settings = {
    AzureWebJobsFeatureFlags       = "EnableWorkerIndexing"
    FUNCTIONS_WORKER_RUNTIME       = "python"
    DOCUMENT_INTELLIGENCE_ENDPOINT = azurerm_cognitive_account.document_intelligence.endpoint
    OUTPUT_CONTAINER_READ          = azurerm_storage_container.invoices_out_read.name
    OUTPUT_CONTAINER_INVOICE       = azurerm_storage_container.invoices_out_invoice.name
    INPUT_CONTAINER                = azurerm_storage_container.invoices_in.name

    # Identity-based connection for blob triggers (blob + queue required) + SDK writes
    "DOCUMENTS_STORAGE__blobServiceUri"  = "https://${azurerm_storage_account.docs.name}.blob.core.windows.net"
    "DOCUMENTS_STORAGE__queueServiceUri" = "https://${azurerm_storage_account.docs.name}.queue.core.windows.net"
    "DOCUMENTS_STORAGE__credential"      = "managedidentity"

    APPINSIGHTS_INSTRUMENTATIONKEY        = azurerm_application_insights.lab1.instrumentation_key
    APPLICATIONINSIGHTS_CONNECTION_STRING = azurerm_application_insights.lab1.connection_string
  }

  tags = azurerm_resource_group.lab1.tags

  depends_on = [
    azurerm_storage_container.invoices_in,
    azurerm_storage_container.invoices_out_read,
    azurerm_storage_container.invoices_out_invoice,
    time_sleep.storage_ready,
  ]

  lifecycle {
    ignore_changes = [
      app_settings["WEBSITE_RUN_FROM_PACKAGE"],
      app_settings["WEBSITE_ENABLE_SYNC_UPDATE_SITE"],
    ]
  }
}

# ---------------------------------------------------------------------------
# Managed Identity RBAC (least privilege)
# ---------------------------------------------------------------------------
resource "azurerm_role_assignment" "func_blob_data" {
  scope                = azurerm_storage_account.docs.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_linux_function_app.ocr.identity[0].principal_id
}

resource "azurerm_role_assignment" "func_di_user" {
  scope                = azurerm_cognitive_account.document_intelligence.id
  role_definition_name = "Cognitive Services User"
  principal_id         = azurerm_linux_function_app.ocr.identity[0].principal_id
}
