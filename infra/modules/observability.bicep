targetScope = 'resourceGroup'

@description('Azure deployment location.')
param location string
@description('Prefix used to name observability resources.')
param resourceNamePrefix string
@allowed([
  30
])
@description('Log retention period in days. The approved value is 30 days.')
param retentionDays int = 30

resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${resourceNamePrefix}-logs'
  location: location
  properties: {
    retentionInDays: retentionDays
    sku: {
      name: 'PerGB2018'
    }
  }
}

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${resourceNamePrefix}-insights'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    IngestionMode: 'LogAnalytics'
    RetentionInDays: retentionDays
    WorkspaceResourceId: logAnalyticsWorkspace.id
  }
}

output logAnalyticsWorkspaceId string = logAnalyticsWorkspace.id
output applicationInsightsResourceId string = applicationInsights.id
output applicationInsightsConnectionString string = applicationInsights.properties.ConnectionString