targetScope = 'resourceGroup'

@description('Azure deployment location.')
param location string
@description('Content-addressed Container App image reference.')
param containerImage string
@description('Existing Azure Container Registry login server.')
param containerRegistryServer string
@description('Existing Azure Container Registry resource ID.')
param containerRegistryResourceId string
@secure()
@description('PostgreSQL administrator password.')
param postgresAdminPassword string
@secure()
@description('The sole destination phone number in E.164 format.')
param myMobileNumber string
@description('ACS source phone number in E.164 format.')
param acsSourcePhoneNumber string
@description('Microsoft Entra tenant ID.')
param entraTenantId string
@description('Microsoft Entra protected-resource client ID.')
param entraClientId string
@secure()
@description('Microsoft Entra client secret.')
param entraClientSecret string
@description('Comma-separated authorized agent application IDs.')
param authorizedAgentAppIds string
@description('Existing ACS resource ID. The resource and source number are external.')
param existingAcsResourceId string

output deploymentLocation string = location
