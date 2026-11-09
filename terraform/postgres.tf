# ---------------------------------------------------------------------------
# Azure Database for PostgreSQL Flexible Server (invoice columns dual-write)
# ---------------------------------------------------------------------------

resource "random_password" "postgres" {
  length           = 24
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "azurerm_postgresql_flexible_server" "invoices" {
  name                   = substr("${var.prefix}-pg-${random_string.suffix.result}", 0, 63)
  resource_group_name    = azurerm_resource_group.lab1.name
  location               = azurerm_resource_group.lab1.location
  version                = var.postgres_version
  administrator_login    = var.postgres_admin_login
  administrator_password = random_password.postgres.result
  sku_name               = var.postgres_sku_name
  storage_mb             = var.postgres_storage_mb
  zone                   = var.postgres_zone

  # Consumption Function + App Service need public access + AllowAzureServices
  # (no fixed outbound IPs / no VNet on Y1). Not reachable without DB password.
  public_network_access_enabled = true

  authentication {
    password_auth_enabled         = true
    active_directory_auth_enabled = false
  }

  tags = azurerm_resource_group.lab1.tags

  lifecycle {
    ignore_changes = [zone]
  }
}

resource "azurerm_postgresql_flexible_server_database" "invoices" {
  name      = var.postgres_database_name
  server_id = azurerm_postgresql_flexible_server.invoices.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

# Consumption Functions have no fixed outbound IP — allow Azure services.
resource "azurerm_postgresql_flexible_server_firewall_rule" "allow_azure" {
  name             = "AllowAzureServices"
  server_id        = azurerm_postgresql_flexible_server.invoices.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

# Allow CREATE EXTENSION vector (pgvector) for RAG chunk embeddings.
resource "azurerm_postgresql_flexible_server_configuration" "azure_extensions" {
  name      = "azure.extensions"
  server_id = azurerm_postgresql_flexible_server.invoices.id
  value     = "VECTOR"
}

locals {
  postgres_database_url = format(
    "postgresql://%s:%s@%s:5432/%s?sslmode=require",
    var.postgres_admin_login,
    urlencode(random_password.postgres.result),
    azurerm_postgresql_flexible_server.invoices.fqdn,
    var.postgres_database_name,
  )
}
