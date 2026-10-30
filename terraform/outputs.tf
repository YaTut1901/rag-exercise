output "resource_group_name" {
  value = azurerm_resource_group.lab1.name
}

output "storage_account_name" {
  value = azurerm_storage_account.docs.name
}

output "function_app_name" {
  value = azurerm_linux_function_app.ocr.name
}

output "document_intelligence_endpoint" {
  value = azurerm_cognitive_account.document_intelligence.endpoint
}

output "document_intelligence_name" {
  value = azurerm_cognitive_account.document_intelligence.name
}

output "input_container" {
  value = azurerm_storage_container.invoices_in.name
}

output "output_container_read" {
  value = azurerm_storage_container.invoices_out_read.name
}

output "output_container_invoice" {
  value = azurerm_storage_container.invoices_out_invoice.name
}

output "upload_example" {
  value = "az storage blob upload --account-name ${azurerm_storage_account.docs.name} --container-name invoices-in --file ./sample.pdf --name sample.pdf --auth-mode login"
}
