targetScope = 'resourceGroup'

@description('Azure deployment location.')
param location string
@description('Prefix used to name Container Apps resources.')
param resourceNamePrefix string
@description('Content-addressed Container App image reference.')
param containerImage string
@description('Explicit Container App target approved for this release.')
param containerAppName string
@description('Revision suffix bound to the reviewed image and source.')
param revisionSuffix string
@description('Existing Azure Container Registry login server.')
param containerRegistryServer string
@description('Existing Azure Container Registry resource ID.')
param containerRegistryResourceId string
@description('User-assigned managed identity resource ID.')
param identityResourceId string
@description('User-assigned managed identity client ID.')
param identityClientId string
@description('Resource ID of the Log Analytics workspace.')
param logAnalyticsWorkspaceId string
@secure()
@description('Application Insights connection string.')
param applicationInsightsConnectionString string
@description('PostgreSQL server fully qualified domain name.')
param databaseHost string
@description('Application database name.')
param databaseName string
@secure()
@description('PostgreSQL administrator password.')
param postgresAdminPassword string
@description('Azure Communication Services endpoint.')
param acsEndpoint string
@description('Azure AI services endpoint.')
param azureAiEndpoint string
@secure()
@description('ACS source phone number in E.164 format.')
param acsSourcePhoneNumber string
@secure()
@description('The sole destination phone number in E.164 format.')
param myMobileNumber string
@description('Microsoft Entra tenant ID.')
param entraTenantId string
@description('Microsoft Entra protected-resource client ID.')
param entraClientId string
@secure()
@description('Microsoft Entra client secret used by Container Apps authentication.')
param entraClientSecret string
@description('Comma-separated authorized agent application IDs.')
param authorizedAgentAppIds string
@description('Audience expected on ACS callback bearer tokens.')
@minLength(1)
param acsCallbackAudience string
@description('Full public HTTPS callback endpoint, including /v1/callbacks/acs.')
param acsCallbackUrl string
@description('Comma-separated hosts accepted by the MCP transport.')
param mcpAllowedHosts string
@description('Speech recognition locale.')
param locale string
@description('Azure AI speech voice name.')
param voiceName string
@description('Application request deadline in seconds.')
param deadlineSeconds int
@description('Latest point at which new call work may begin, in seconds.')
param workCutoffSeconds int
@description('Request status polling interval in milliseconds.')
param pollIntervalMilliseconds int
@description('Terminal request retention period in hours.')
param retentionHours int

var containerAppsEnvironmentName = '${resourceNamePrefix}-environment'
var postgresAdministratorLogin = 'askmyhumanadmin'
var registryResourceIdSegments = split(containerRegistryResourceId, '/')
var registrySubscriptionId = registryResourceIdSegments[2]
var registryResourceGroupName = registryResourceIdSegments[4]
var registryName = registryResourceIdSegments[8]

resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: last(split(logAnalyticsWorkspaceId, '/'))
}

resource containerIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: last(split(identityResourceId, '/'))
}

module registryPullRoleAssignment 'container-app-acr-role-assignment.bicep' = {
  name: '${containerAppName}-acr-pull'
  scope: resourceGroup(registrySubscriptionId, registryResourceGroupName)
  params: {
    containerRegistryName: registryName
    principalId: containerIdentity.properties.principalId
  }
}

resource containerAppsEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: containerAppsEnvironmentName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsWorkspace.properties.customerId
        sharedKey: logAnalyticsWorkspace.listKeys().primarySharedKey
      }
    }
    zoneRedundant: false
  }
}

resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: containerAppName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identityResourceId}': {}
    }
  }
  properties: {
    environmentId: containerAppsEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        allowInsecure: false
        external: true
        targetPort: 8000
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
        transport: 'auto'
      }
      registries: [
        {
          identity: identityResourceId
          server: containerRegistryServer
        }
      ]
      secrets: [
        {
          name: 'application-insights-connection-string'
          value: applicationInsightsConnectionString
        }
        {
          name: 'database-url'
          #disable-next-line use-secure-value-for-secure-inputs
          value: 'postgresql+psycopg://${postgresAdministratorLogin}:${uriComponent(postgresAdminPassword)}@${databaseHost}:5432/${databaseName}?sslmode=require'
        }
        {
          name: 'acs-source-phone-number'
          value: acsSourcePhoneNumber
        }
        {
          name: 'my-mobile-number'
          value: myMobileNumber
        }
        {
          name: 'entra-client-secret'
          value: entraClientSecret
        }
      ]
    }
    template: {
      revisionSuffix: revisionSuffix
      containers: [
        {
          name: 'ask-my-human'
          image: containerImage
          env: [
            {
              name: 'AZURE_CLIENT_ID'
              value: identityClientId
            }
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              secretRef: 'application-insights-connection-string'
            }
            {
              name: 'DATABASE_URL'
              secretRef: 'database-url'
            }
            {
              name: 'ACS_ENDPOINT'
              value: acsEndpoint
            }
            {
              name: 'ACS_SOURCE_PHONE_NUMBER'
              secretRef: 'acs-source-phone-number'
            }
            {
              name: 'MY_MOBILE_NUMBER'
              secretRef: 'my-mobile-number'
            }
            {
              name: 'AZURE_AI_ENDPOINT'
              value: azureAiEndpoint
            }
            {
              name: 'ACS_CALLBACK_AUDIENCE'
              value: acsCallbackAudience
            }
            {
              name: 'ACS_CALLBACK_URL'
              value: acsCallbackUrl
            }
            {
              name: 'ENTRA_TENANT_ID'
              value: entraTenantId
            }
            {
              name: 'ENTRA_CLIENT_ID'
              value: entraClientId
            }
            {
              name: 'AUTHORIZED_AGENT_APP_IDS'
              value: authorizedAgentAppIds
            }
            {
              name: 'MCP_ALLOWED_HOSTS'
              value: mcpAllowedHosts
            }
            {
              name: 'LOCALE'
              value: locale
            }
            {
              name: 'VOICE_NAME'
              value: voiceName
            }
            {
              name: 'DEADLINE_SECONDS'
              value: string(deadlineSeconds)
            }
            {
              name: 'WORK_CUTOFF_SECONDS'
              value: string(workCutoffSeconds)
            }
            {
              name: 'POLL_INTERVAL_MILLISECONDS'
              value: string(pollIntervalMilliseconds)
            }
            {
              name: 'RETENTION_HOURS'
              value: string(retentionHours)
            }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/health/live'
                port: 8000
                scheme: 'HTTP'
              }
              initialDelaySeconds: 10
              periodSeconds: 10
              timeoutSeconds: 5
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/health/ready'
                port: 8000
                scheme: 'HTTP'
              }
              initialDelaySeconds: 5
              periodSeconds: 5
              timeoutSeconds: 5
              failureThreshold: 3
              successThreshold: 1
            }
          ]
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
  dependsOn: [
    registryPullRoleAssignment
  ]
}

resource authConfig 'Microsoft.App/containerApps/authConfigs@2024-03-01' = {
  parent: containerApp
  name: 'current'
  properties: {
    globalValidation: {
      excludedPaths: [
        '/v1/callbacks/acs'
      ]
      unauthenticatedClientAction: 'Return401'
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: entraClientId
          clientSecretSettingName: 'entra-client-secret'
          openIdIssuer: '${environment().authentication.loginEndpoint}${entraTenantId}/v2.0'
        }
        validation: {
          allowedAudiences: [
            'api://${entraClientId}'
            entraClientId
          ]
          defaultAuthorizationPolicy: {
            allowedApplications: split(authorizedAgentAppIds, ',')
          }
        }
      }
    }
    login: {
      tokenStore: {
        enabled: false
      }
    }
    platform: {
      enabled: true
      runtimeVersion: '~1'
    }
  }
}

output containerAppName string = containerApp.name
output containerAppResourceId string = containerApp.id
output fqdn string = containerApp.properties.configuration.ingress.fqdn