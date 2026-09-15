targetScope = 'resourceGroup'

// Phase 0 intentionally freezes the deployment input contract; modules land in later phases.
@description('Azure deployment location.')
param location string
@description('Content-addressed Container App image reference.')
#disable-next-line no-unused-params
param containerImage string
@description('Existing Azure Container Registry login server.')
#disable-next-line no-unused-params
param containerRegistryServer string
@description('Existing Azure Container Registry resource ID.')
#disable-next-line no-unused-params
param containerRegistryResourceId string
@secure()
@description('PostgreSQL administrator password.')
#disable-next-line no-unused-params
param postgresAdminPassword string
@secure()
@description('The sole destination phone number in E.164 format.')
#disable-next-line no-unused-params
param myMobileNumber string
@description('ACS source phone number in E.164 format.')
#disable-next-line no-unused-params
param acsSourcePhoneNumber string
@description('Microsoft Entra tenant ID.')
#disable-next-line no-unused-params
param entraTenantId string
@description('Microsoft Entra protected-resource client ID.')
#disable-next-line no-unused-params
param entraClientId string
@secure()
@description('Microsoft Entra client secret.')
#disable-next-line no-unused-params
param entraClientSecret string
@description('Comma-separated authorized agent application IDs.')
#disable-next-line no-unused-params
param authorizedAgentAppIds string
@description('Existing ACS resource ID. The resource and source number are external.')
#disable-next-line no-unused-params
param existingAcsResourceId string

output deploymentLocation string = location
