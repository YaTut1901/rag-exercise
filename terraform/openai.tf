# ---------------------------------------------------------------------------
# Azure OpenAI (embeddings + chat for lab-3 RAG)
# Often unavailable in switzerlandnorth — use openai_location.
# ---------------------------------------------------------------------------

locals {
  openai_name = substr("${var.prefix}-oai-${random_string.suffix.result}", 0, 64)
}

resource "azurerm_cognitive_account" "openai" {
  name                  = local.openai_name
  location              = var.openai_location
  resource_group_name   = azurerm_resource_group.lab1.name
  kind                  = "OpenAI"
  sku_name              = "S0"
  custom_subdomain_name = local.openai_name

  public_network_access_enabled = true

  tags = azurerm_resource_group.lab1.tags
}

resource "azurerm_cognitive_deployment" "embeddings" {
  name                 = var.openai_embedding_deployment_name
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = var.openai_embedding_model_name
    version = var.openai_embedding_model_version
  }

  sku {
    # text-embedding-3-small is GlobalStandard-only in several EU regions
    name     = var.openai_embedding_sku
    capacity = var.openai_embedding_capacity
  }
}

resource "azurerm_cognitive_deployment" "chat" {
  name                 = var.openai_chat_deployment_name
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = var.openai_chat_model_name
    version = var.openai_chat_model_version
  }

  sku {
    name     = var.openai_chat_sku
    capacity = var.openai_chat_capacity
  }
}

resource "azurerm_role_assignment" "func_openai_user" {
  scope                = azurerm_cognitive_account.openai.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_linux_function_app.ocr.identity[0].principal_id
}
