targetScope = 'resourceGroup'

@description('Azure deployment location.')
param location string
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
@secure()
@description('PostgreSQL administrator password.')
param postgresAdminPassword string
@secure()
@description('The sole destination phone number in E.164 format.')
param myMobileNumber string
@secure()
@description('ACS source phone number in E.164 format.')
param acsSourcePhoneNumber string
@description('Microsoft Entra tenant ID.')
param entraTenantId string
@description('Microsoft Entra protected-resource client ID.')
param entraClientId string
@secure()
@description('Microsoft Entra client secret.')
param entraClientSecret string
@description('Comma-separated authorized agent application IDs.')
param authorizedAgentAppIds string
@description('Existing ACS resource ID. The resource and source number are external.')
param existingAcsResourceId string
@description('Verified ACS properties.immutableResourceId expected as the callback JWT audience, not an ARM ID or URL.')
@minLength(1)
param acsCallbackAudience string
@description('Full public HTTPS callback endpoint, including /v1/callbacks/acs.')
param acsCallbackUrl string
@description('Comma-separated public hosts accepted by the MCP transport.')
param mcpAllowedHosts string

var resourceNamePrefix = 'askmyhuman-${uniqueString(resourceGroup().id)}'

module identity 'modules/identity.bicep' = {
	name: 'askmyhuman-identity'
	params: {
		location: location
		resourceNamePrefix: resourceNamePrefix
	}
}

module observability 'modules/observability.bicep' = {
	name: 'askmyhuman-observability'
	params: {
		location: location
		resourceNamePrefix: resourceNamePrefix
		retentionDays: 30
	}
}

module postgresql 'modules/postgresql.bicep' = {
	name: 'askmyhuman-postgresql'
	params: {
		location: location
		resourceNamePrefix: resourceNamePrefix
		administratorPassword: postgresAdminPassword
		databaseName: 'askmyhuman'
		serverVersion: '16'
	}
}

module communications 'modules/communications.bicep' = {
	name: 'askmyhuman-communications'
	params: {
		location: location
		resourceNamePrefix: resourceNamePrefix
		existingAcsResourceId: existingAcsResourceId
		containerIdentityPrincipalId: identity.outputs.principalId
		containerIdentityResourceId: identity.outputs.identityResourceId
		logAnalyticsWorkspaceId: observability.outputs.logAnalyticsWorkspaceId
	}
}

module containerApp 'modules/container-app.bicep' = {
	name: 'askmyhuman-container-app'
	params: {
		location: location
		resourceNamePrefix: resourceNamePrefix
		containerImage: containerImage
		containerAppName: containerAppName
		revisionSuffix: revisionSuffix
		containerRegistryServer: containerRegistryServer
		containerRegistryResourceId: containerRegistryResourceId
		identityResourceId: identity.outputs.identityResourceId
		identityClientId: identity.outputs.clientId
		logAnalyticsWorkspaceId: observability.outputs.logAnalyticsWorkspaceId
		applicationInsightsConnectionString: observability.outputs.applicationInsightsConnectionString
		databaseHost: postgresql.outputs.databaseHost
		databaseName: postgresql.outputs.databaseName
		postgresAdminPassword: postgresAdminPassword
		acsEndpoint: communications.outputs.acsEndpoint
		azureAiEndpoint: communications.outputs.azureAiEndpoint
		acsSourcePhoneNumber: acsSourcePhoneNumber
		myMobileNumber: myMobileNumber
		entraTenantId: entraTenantId
		entraClientId: entraClientId
		entraClientSecret: entraClientSecret
		authorizedAgentAppIds: authorizedAgentAppIds
		acsCallbackAudience: acsCallbackAudience
		acsCallbackUrl: acsCallbackUrl
		mcpAllowedHosts: mcpAllowedHosts
		locale: 'en-US'
		voiceName: 'en-US-AvaMultilingualNeural'
		deadlineSeconds: 210
		workCutoffSeconds: 205
		pollIntervalMilliseconds: 500
		retentionHours: 24
	}
}

output deploymentLocation string = location
output containerAppName string = containerApp.outputs.containerAppName
output containerAppResourceId string = containerApp.outputs.containerAppResourceId
output fqdn string = containerApp.outputs.fqdn
