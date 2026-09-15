targetScope = 'resourceGroup'

@description('Azure deployment location.')
param location string

@description('Prefix used to name deployed resources.')
param resourceNamePrefix string

@description('Resource ID of an existing ACS resource with an outbound-enabled source number and a system-assigned managed identity.')
param existingAcsResourceId string

@description('Principal ID of the Container App user-assigned managed identity.')
param containerIdentityPrincipalId string

var acsResourceIdSegments = split(existingAcsResourceId, '/')
var acsSubscriptionId = acsResourceIdSegments[2]
var acsResourceGroupName = acsResourceIdSegments[4]
var acsResourceName = acsResourceIdSegments[8]
var azureAiResourceName = toLower('${resourceNamePrefix}-ai')
var cognitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908'

resource acs 'Microsoft.Communication/communicationServices@2023-04-01' existing = {
  name: acsResourceName
  scope: resourceGroup(acsSubscriptionId, acsResourceGroupName)
}

resource azureAi 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: azureAiResourceName
  location: location
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: azureAiResourceName
    publicNetworkAccess: 'Enabled'
  }
}

module containerAcsDataOwner 'communications-acs-role-assignment.bicep' = {
  name: 'communications-acs-role-assignment'
  scope: resourceGroup(acsSubscriptionId, acsResourceGroupName)
  params: {
    acsResourceName: acsResourceName
    containerIdentityPrincipalId: containerIdentityPrincipalId
  }
}

resource acsAzureAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(azureAi.id, acs.id, cognitiveServicesUserRoleId)
  scope: azureAi
  properties: {
    principalId: acs.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleId)
  }
}

output acsResourceId string = acs.id
output acsEndpoint string = 'https://${acs.properties.hostName}'
output azureAiResourceId string = azureAi.id
output azureAiEndpoint string = azureAi.properties.endpoint