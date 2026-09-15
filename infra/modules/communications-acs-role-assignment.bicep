targetScope = 'resourceGroup'

@description('Name of the existing ACS resource.')
param acsResourceName string

@description('Principal ID of the Container App user-assigned managed identity.')
param containerIdentityPrincipalId string

var azureCommunicationServicesDataOwnerRoleId = '0d8b7e87-0907-4e9d-a49d-ad2166c4bf2e'

resource acs 'Microsoft.Communication/communicationServices@2023-04-01' existing = {
  name: acsResourceName
}

resource containerAcsDataOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acs.id, containerIdentityPrincipalId, azureCommunicationServicesDataOwnerRoleId)
  scope: acs
  properties: {
    principalId: containerIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      azureCommunicationServicesDataOwnerRoleId
    )
  }
}