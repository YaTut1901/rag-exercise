# ---------------------------------------------------------------------------
# Streamlit UI (public HTTPS) — only intentional public entry point for the lab
# ---------------------------------------------------------------------------

locals {
  ui_name = substr("${var.prefix}-ui-${random_string.suffix.result}", 0, 60)
}

resource "azurerm_service_plan" "ui" {
  name                = "${var.prefix}-ui-plan-${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.lab1.name
  location            = azurerm_resource_group.lab1.location
  os_type             = "Linux"
  sku_name            = var.ui_sku_name

  tags = azurerm_resource_group.lab1.tags
}

resource "azurerm_linux_web_app" "ui" {
  name                = local.ui_name
  resource_group_name = azurerm_resource_group.lab1.name
  location            = azurerm_resource_group.lab1.location
  service_plan_id     = azurerm_service_plan.ui.id

  https_only                    = true
  public_network_access_enabled = true

  identity {
    type = "SystemAssigned"
  }

  site_config {
    always_on                         = var.ui_sku_name != "F1"
    ftps_state                        = "Disabled"
    minimum_tls_version               = "1.2"
    ip_restriction_default_action     = "Allow"
    scm_ip_restriction_default_action = "Allow"

    application_stack {
      python_version = "3.11"
    }

    # Deps preinstalled into .python_packages (remote Oryx pip OOMs on B1).
    app_command_line = "bash -c 'export PYTHONPATH=/home/site/wwwroot/.python_packages/lib/site-packages:$PYTHONPATH; python -m streamlit run app.py --server.port=8000 --server.address=0.0.0.0 --server.headless=true --browser.gatherUsageStats=false'"
  }

  app_settings = {
    WEBSITES_PORT                  = "8000"
    SCM_DO_BUILD_DURING_DEPLOYMENT = "false"
    ENABLE_ORYX_BUILD              = "false"
    PYTHONPATH                     = "/home/site/wwwroot/.python_packages/lib/site-packages"

    AZURE_OPENAI_ENDPOINT             = azurerm_cognitive_account.openai.endpoint
    AZURE_OPENAI_CHAT_DEPLOYMENT      = azurerm_cognitive_deployment.chat.name
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT = azurerm_cognitive_deployment.embeddings.name
    AZURE_OPENAI_EMBEDDING_DIMENSIONS = tostring(var.openai_embedding_dimensions)
    AZURE_OPENAI_API_VERSION          = "2024-10-21"

    DATABASE_URL = local.postgres_database_url

    "DOCUMENTS_STORAGE__blobServiceUri" = "https://${azurerm_storage_account.docs.name}.blob.core.windows.net"
    INPUT_CONTAINER                     = azurerm_storage_container.invoices_in.name
    OUTPUT_CONTAINER_INVOICE            = azurerm_storage_container.invoices_out_invoice.name
    OUTPUT_CONTAINER_READ               = azurerm_storage_container.invoices_out_read.name

    APPINSIGHTS_INSTRUMENTATIONKEY        = azurerm_application_insights.lab1.instrumentation_key
    APPLICATIONINSIGHTS_CONNECTION_STRING = azurerm_application_insights.lab1.connection_string
  }

  tags = azurerm_resource_group.lab1.tags

  depends_on = [
    azurerm_postgresql_flexible_server_firewall_rule.allow_azure,
    azurerm_cognitive_deployment.embeddings,
    azurerm_cognitive_deployment.chat,
    azurerm_storage_container.invoices_in,
  ]

  lifecycle {
    ignore_changes = [
      app_settings["WEBSITE_RUN_FROM_PACKAGE"],
    ]
  }
}

resource "azurerm_role_assignment" "ui_blob_data" {
  scope                = azurerm_storage_account.docs.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_linux_web_app.ui.identity[0].principal_id
}

resource "azurerm_role_assignment" "ui_openai_user" {
  scope                = azurerm_cognitive_account.openai.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_linux_web_app.ui.identity[0].principal_id
}

locals {
  ui_outbound_ips = distinct(compact(concat(
    split(",", azurerm_linux_web_app.ui.outbound_ip_addresses),
    split(",", azurerm_linux_web_app.ui.possible_outbound_ip_addresses),
  )))
}

# App Service is NOT covered by bypass=AzureServices; allow its outbound IPs.
resource "azurerm_storage_account_network_rules" "docs" {
  storage_account_id = azurerm_storage_account.docs.id

  default_action             = "Deny"
  bypass                     = ["AzureServices"]
  ip_rules                   = local.ui_outbound_ips
  virtual_network_subnet_ids = []
}
