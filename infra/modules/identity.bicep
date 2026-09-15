targetScope = 'resourceGroup'

@description('Azure deployment location.')
param location string

@description('Prefix used to name deployed resources.')
param resourceNamePrefix string

resource containerIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${resourceNamePrefix}-identity'
  location: location
}

output identityResourceId string = containerIdentity.id
output principalId string = containerIdentity.properties.principalId
output clientId string = containerIdentity.properties.clientId