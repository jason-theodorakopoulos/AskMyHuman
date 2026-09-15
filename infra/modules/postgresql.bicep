targetScope = 'resourceGroup'

@description('Azure deployment location.')
param location string
@description('Prefix used to name PostgreSQL resources.')
param resourceNamePrefix string
@description('Resource ID of the subnet delegated to PostgreSQL Flexible Server.')
param delegatedSubnetId string
@description('Resource ID of the PostgreSQL private DNS zone.')
param privateDnsZoneId string
@secure()
@description('PostgreSQL administrator password.')
param administratorPassword string
@description('Application database name.')
param databaseName string
@allowed([
  '16'
])
@description('PostgreSQL major server version.')
param serverVersion string

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
      delegatedSubnetResourceId: delegatedSubnetId
      privateDnsZoneArmResourceId: privateDnsZoneId
      publicNetworkAccess: 'Disabled'
    }
    storage: {
      storageSizeGB: 32
    }
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

output serverResourceId string = server.id
output databaseHost string = server.properties.fullyQualifiedDomainName
output databaseName string = applicationDatabase.name