// Dottie's shared infrastructure: Log Analytics, a registry with the identity apps pull with, PostgreSQL and the
// Container Apps environment. No apps: those are app.bicep, deployed on their own (scripts/azure-deploy.sh).
// Changes here are rare; scripts/azure-up.sh deploys this file, then the app.

@description('Region for everything.')
param location string = resourceGroup().location

@description('Object id of whoever deploys (az ad signed-in-user show): also a PostgreSQL admin, for psql and fixes.')
param adminObjectId string

@description('That person\'s user principal name (their sign-in name).')
param adminName string

@description('Region of the Container Apps environment (and so the app). Differs from `location` when that region has no capacity for it.')
param appLocation string = location

// every name derives from the resource group, so app.bicep finds the same resources without parameters
var suffix = take(uniqueString(resourceGroup().id), 6)

resource logs 'Microsoft.OperationalInsights/workspaces@2025-02-01' = {
  name: 'log-${suffix}'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

// -- registry, and the identity apps pull with (no admin user, no registry password) ----------------------------------
resource acr 'Microsoft.ContainerRegistry/registries@2025-04-01' = {
  name: 'acr${suffix}'
  location: location
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: 'id-${suffix}'
  location: location
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, identity.id, 'acrpull')
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// -- PostgreSQL: the smallest Flexible Server (Burstable B1ms), Entra sign-in only (no password exists) ----------------
resource pg 'Microsoft.DBforPostgreSQL/flexibleServers@2025-08-01' = {
  name: 'pg-${suffix}'
  location: location
  sku: { name: 'Standard_B1ms', tier: 'Burstable' }
  properties: {
    version: '18' // the same major as compose.yaml and CI
    storage: { storageSizeGB: 32, autoGrow: 'Disabled' }
    backup: { backupRetentionDays: 7, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }
    network: { publicNetworkAccess: 'Enabled' }
    authConfig: { passwordAuth: 'Disabled', activeDirectoryAuth: 'Enabled', tenantId: tenant().tenantId }
  }
}

// the app signs in as its managed identity (DATABASE_ENTRA_AUTH); it runs the migrations, so it is an admin
module pgAdminApp 'modules/pg-admin.bicep' = {
  name: 'pg-admin-app'
  params: { serverName: pg.name, objectId: identity.properties.principalId, principalName: identity.name, principalType: 'ServicePrincipal' }
}

module pgAdminDeployer 'modules/pg-admin.bicep' = {
  name: 'pg-admin-deployer'
  dependsOn: [pgAdminApp] // one administrator change at a time
  params: { serverName: pg.name, objectId: adminObjectId, principalName: adminName, principalType: 'User' }
}

// Trade-off: 0.0.0.0 lets Azure services of any tenant reach the server (they still need an Entra token for it).
// Private networking (a VNet for the environment, private access for the server) closes that, at a cost.
resource pgAllowAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2025-08-01' = {
  parent: pg
  name: 'AllowAzureServices'
  properties: { startIpAddress: '0.0.0.0', endIpAddress: '0.0.0.0' }
}

resource pgDb 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2025-08-01' = {
  parent: pg
  name: 'dottie'
  properties: { charset: 'UTF8', collation: 'en_US.utf8' }
}

// -- The model: an Azure AI Services (Foundry) account with one deployment, Entra sign-in only (no key exists) ---------
@description('The model deployment dotties think with.')
param modelName string = 'gpt-6-luna'

@description('Model version.')
param modelVersion string = '2026-09-22'

@description('Capacity in thousands of tokens per minute.')
param modelCapacity int = 50

resource ai 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: 'ais-${suffix}'
  location: location
  kind: 'AIServices'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: 'ais-${suffix}'
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
  }
}

resource model 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: ai
  name: modelName
  sku: { name: 'GlobalStandard', capacity: modelCapacity }
  properties: { model: { format: 'OpenAI', name: modelName, version: modelVersion } }
}

resource openAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: ai
  name: guid(ai.id, identity.id, 'openai-user')
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd') // Cognitive Services OpenAI User
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// -- Container Apps environment (Consumption) ---------------------------------------------------------------------------
resource env 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: 'cae-${suffix}'
  location: appLocation
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
    workloadProfiles: [{ name: 'Consumption', workloadProfileType: 'Consumption' }]
  }
}

output acrName string = acr.name
output acrLoginServer string = acr.properties.loginServer
output envDomain string = env.properties.defaultDomain
output modelDeployment string = model.name
output suffix string = suffix
output identityPrincipalId string = identity.properties.principalId
