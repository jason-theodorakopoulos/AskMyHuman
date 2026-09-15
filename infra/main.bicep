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
@secure()
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

// Frozen Phase 1B module contracts. Module owners implement these exact surfaces
// without changing this composition root.
// identity.bicep
//   inputs: location, resourceNamePrefix
//   outputs: identityResourceId, principalId, clientId
// observability.bicep
//   inputs: location, resourceNamePrefix, retentionDays
//   outputs: logAnalyticsWorkspaceId, applicationInsightsResourceId, applicationInsightsConnectionString
// postgresql.bicep
//   inputs: location, resourceNamePrefix, administratorPassword, databaseName,
//           serverVersion
//   outputs: serverResourceId, databaseHost, databaseName
// communications.bicep
//   inputs: location, resourceNamePrefix, existingAcsResourceId,
//           containerIdentityPrincipalId
//   outputs: acsResourceId, acsEndpoint, azureAiResourceId, azureAiEndpoint
// container-app.bicep
//   inputs: location, resourceNamePrefix, containerImage, containerRegistryServer,
//           containerRegistryResourceId, identityResourceId, identityClientId,
//           logAnalyticsWorkspaceId, applicationInsightsConnectionString,
//           databaseHost, databaseName, postgresAdminPassword, acsEndpoint,
//           azureAiEndpoint, acsSourcePhoneNumber, myMobileNumber, entraTenantId,
//           entraClientId, entraClientSecret, authorizedAgentAppIds,
//           acsCallbackAudience, mcpAllowedHosts, locale, voiceName,
//           deadlineSeconds, workCutoffSeconds, pollIntervalMilliseconds,
//           retentionHours
//   outputs: containerAppName, containerAppResourceId, fqdn

output deploymentLocation string = location
