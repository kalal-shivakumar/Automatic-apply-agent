variable "subscription_id" {
  description = "Azure subscription ID"
  type        = string
  default     = "eea9ffc5-6c64-4dab-b152-3d2f49a73ff1"
}

variable "resource_group_name" {
  description = "Name of the resource group"
  type        = string
  default     = "rg-naukri-agent"
}

variable "location" {
  description = "Azure region"
  type        = string
  default     = "eastus"
}

variable "openai_account_name" {
  description = "Azure OpenAI service account name"
  type        = string
  default     = "naukri-agent-ai"
}

variable "openai_deployment_name" {
  description = "Model deployment name"
  type        = string
  default     = "gpt-5.4-mini"
}

variable "openai_model_name" {
  description = "OpenAI model name"
  type        = string
  default     = "gpt-5.4-mini"
}

variable "openai_model_version" {
  description = "Model version"
  type        = string
  default     = "2026-03-17"
}

variable "openai_capacity" {
  description = "Token-per-minute capacity (in thousands)"
  type        = number
  default     = 10
}
