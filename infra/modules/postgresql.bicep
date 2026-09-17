targetScope = 'resourceGroup'

@description('Azure deployment location.')
param location string
@description('Prefix used to name PostgreSQL resources.')
param resourceNamePrefix string
@secure()
@description('PostgreSQL administrator password.')
param administratorPassword string
@description('Application database name.')
param databaseName string
@description('Provision a dedicated database for destructive live validation.')
param provisionLiveDatabase bool = false
@description('Bind the application output to the dedicated live database.')
param useLiveDatabase bool = false
@allowed([
  '16'
])
@description('PostgreSQL major server version.')
param serverVersion string

var liveDatabaseName = '${databaseName}_live'

var serverName = toLower('${resourceNamePrefix}-postgres-${uniqueString(resourceGroup().id)}')
var administratorLogin = 'askmyhumanadmin'

resource server 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: serverName
  location: location
  sku: {
    name: 'Standard_B1ms'
    tier: 'Burstable'
  }
  properties: {
    administratorLogin: administratorLogin
    administratorLoginPassword: administratorPassword
    version: serverVersion
    authConfig: {
      activeDirectoryAuth: 'Disabled'
      passwordAuth: 'Enabled'
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: {
      mode: 'Disabled'
    }
    network: {
      publicNetworkAccess: 'Enabled'
    }
    storage: {
      storageSizeGB: 32
    }
  }
}

resource allowAzureServices 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
  parent: server
  name: 'AllowAllAzureServicesAndResourcesWithinAzureIps'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

resource requireSecureTransport 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
  parent: server
  name: 'require_secure_transport'
  properties: {
    source: 'user-override'
    value: 'on'
  }
}

resource minimumTlsVersion 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
  parent: server
  name: 'ssl_min_protocol_version'
  properties: {
    source: 'user-override'
    value: 'TLSv1.2'
  }
}

resource applicationDatabase 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: server
  name: databaseName
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

resource liveDatabase 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = if (provisionLiveDatabase || useLiveDatabase) {
  parent: server
  name: liveDatabaseName
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

output serverResourceId string = server.id
output databaseHost string = server.properties.fullyQualifiedDomainName
output databaseName string = useLiveDatabase ? liveDatabaseName : applicationDatabase.name
output liveDatabaseName string = liveDatabaseName