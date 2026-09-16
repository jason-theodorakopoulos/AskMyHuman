targetScope = 'resourceGroup'

@description('Existing Azure Container Registry name.')
param containerRegistryName string
@description('Managed identity principal ID granted pull access.')
param principalId string

@description('Resource ID of the managed identity; names the assignment without a runtime reference.')
param principalResourceId string

var acrPullRoleDefinitionId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: containerRegistryName
}

resource registryPullRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(containerRegistry.id, principalResourceId, acrPullRoleDefinitionId)
  scope: containerRegistry
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleDefinitionId)
  }
}