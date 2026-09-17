targetScope = 'resourceGroup'

@description('Name of the existing ACS resource.')
param acsResourceName string

@description('Resource ID of the Log Analytics workspace receiving ACS diagnostics.')
param logAnalyticsWorkspaceId string

resource acs 'Microsoft.Communication/communicationServices@2023-04-01' existing = {
  name: acsResourceName
}

resource acsDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'askmyhuman-call-automation'
  scope: acs
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logAnalyticsDestinationType: 'Dedicated'
    logs: [
      {
        category: 'CallAutomationOperational'
        enabled: true
      }
      {
        category: 'CallAutomationMediaSummary'
        enabled: true
      }
    ]
  }
}