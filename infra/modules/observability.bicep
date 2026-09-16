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
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
    retentionInDays: retentionDays
    features: {
      immediatePurgeDataOn30Days: true
    }
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
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
    RetentionInDays: retentionDays
    WorkspaceResourceId: logAnalyticsWorkspace.id
  }
}

var applicationTables = [
  'AppAvailabilityResults'
  'AppBrowserTimings'
  'AppDependencies'
  'AppEvents'
  'AppExceptions'
  'AppMetrics'
  'AppPageViews'
  'AppPerformanceCounters'
  'AppRequests'
  'AppTraces'
]

resource applicationTableRetention 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = [for tableName in applicationTables: {
  parent: logAnalyticsWorkspace
  name: tableName
  properties: {
    retentionInDays: retentionDays
    totalRetentionInDays: retentionDays
  }
  dependsOn: [
    applicationInsights
  ]
}]

output logAnalyticsWorkspaceId string = logAnalyticsWorkspace.id
output applicationInsightsResourceId string = applicationInsights.id
output applicationInsightsConnectionString string = applicationInsights.properties.ConnectionString