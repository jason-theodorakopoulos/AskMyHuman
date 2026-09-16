targetScope = 'resourceGroup'

@description('Name of the existing ACS resource.')
param acsResourceName string

@description('Principal ID of the Container App user-assigned managed identity.')
param containerIdentityPrincipalId string

@description('Resource ID of the managed identity; names the assignment without a runtime reference.')
param containerIdentityResourceId string

// ACS has no dataActions model; this is the role that grants managed identity access to the resource.
var communicationAndEmailServiceOwnerRoleId = '09976791-48a7-449e-bb21-39d1a415f350'

resource acs 'Microsoft.Communication/communicationServices@2023-04-01' existing = {
  name: acsResourceName
}

resource containerAcsDataOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acs.id, containerIdentityResourceId, communicationAndEmailServiceOwnerRoleId)
  scope: acs
  properties: {
    principalId: containerIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      communicationAndEmailServiceOwnerRoleId
    )
  }
}