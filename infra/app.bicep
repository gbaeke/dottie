// One Container App on the existing infrastructure (main.bicep): only this resource changes on a deploy.
// scripts/azure-deploy.sh builds and pushes the image, then deploys this file. Another app or a worker in the same
// environment is another deployment of this file with its own name and image.

@description('Region of the app: the Container Apps environment\'s.')
param location string = resourceGroup().location

@description('Region of the sandbox group (the infrastructure\'s).')
param sandboxRegion string = resourceGroup().location

@description('The Container App\'s name; also its host name.')
param name string = 'dottie'

@description('Image to run: <registry>.azurecr.io/dottie:<tag>.')
param image string

@description('Ingress IP rules (ipSecurityRestrictions). Empty: open to every address.')
param ipRules array = []

@description('What "now" means to the dotties (an IANA time zone).')
param userTimezone string = 'Europe/Brussels'

@description('all: the whole app. internal: only the API the agents in the sandboxes call back to (the gateway app).')
@allowed(['all', 'internal'])
param serve string = 'all'

@description('Where the agent loop runs: in this app, or inside the dottie\'s own sandbox.')
@allowed(['app', 'sandbox'])
param agentMode string = 'sandbox'

@description('How a sandbox reaches the app\'s callback API (the gateway\'s address). Needed with agentMode sandbox.')
param gatewayUrl string = ''

@description('WorkOS client id: the app\'s own sign-in (AuthKit), for many users. Empty: no sign-in.')
param workosClientId string = ''

@secure()
param workosApiKey string = ''

@secure()
@description('Encrypts the session cookie (SESSION_SECRET); changing it signs everyone out.')
param sessionSecret string = ''

@description('Comma separated emails the app lets in (ALLOWED_USERS). Empty: everyone WorkOS lets in.')
param allowedUsers string = ''

@secure()
@description('Encrypts the secrets users store (SECRETS_KEY). Both apps need it: the gateway runs the tools in sandbox mode.')
param secretsKey string = ''

@secure()
@description('The Telegram bot\'s token (TELEGRAM_BOT_TOKEN), from @BotFather. Empty: no Telegram. Both apps need it.')
param telegramBotToken string = ''

@description('Most dotties one user may have.')
param maxDottiesPerUser int = 20

@description('Seconds a dottie\'s sandbox stays running after its last run, for follow-up messages.')
param sandboxIdleSeconds int = 120

@description('The model deployment name (main.bicep).')
param modelName string = 'gpt-6-luna'

// the same names main.bicep gives its resources
var suffix = take(uniqueString(resourceGroup().id), 6)

resource env 'Microsoft.App/managedEnvironments@2025-01-01' existing = {
  name: 'cae-${suffix}'
}

resource acr 'Microsoft.ContainerRegistry/registries@2025-04-01' existing = {
  name: 'acr${suffix}'
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' existing = {
  name: 'id-${suffix}'
}

resource pg 'Microsoft.DBforPostgreSQL/flexibleServers@2025-08-01' existing = {
  name: 'pg-${suffix}'
}

resource ai 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: 'ais-${suffix}'
}

// no password: the app signs in with a token for its managed identity (db.py), so this is not a secret
var databaseUrl = 'postgresql://${identity.name}@${pg.properties.fullyQualifiedDomainName}:5432/dottie?sslmode=require'

// sign-in is the app's, not the gateway's (which answers sandboxes with run tokens)
var withWorkos = serve == 'all' && !empty(workosClientId)
// PUBLIC_URL: behind the ingress the app sees http, and builds the sign-in callback URL from this instead
var workosEnv = withWorkos
  ? concat(
      [
        { name: 'WORKOS_CLIENT_ID', value: workosClientId }
        { name: 'WORKOS_API_KEY', secretRef: 'workos-api-key' }
        { name: 'SESSION_SECRET', secretRef: 'session-secret' }
        { name: 'PUBLIC_URL', value: 'https://${name}.${env.properties.defaultDomain}' }
        { name: 'MAX_DOTTIES_PER_USER', value: string(maxDottiesPerUser) }
      ],
      empty(allowedUsers) ? [] : [{ name: 'ALLOWED_USERS', value: allowedUsers }]
    )
  : []
// both apps need the bot: the app has its webhook and sends the answers, the gateway runs the tools (send_telegram)
// of an agent in a sandbox. The webhook address is PUBLIC_URL, which the app has with sign-in.
var withTelegram = !empty(telegramBotToken)
var secrets = concat(
  withWorkos ? [{ name: 'workos-api-key', value: workosApiKey }, { name: 'session-secret', value: sessionSecret }] : [],
  empty(secretsKey) ? [] : [{ name: 'secrets-key', value: secretsKey }],
  withTelegram ? [{ name: 'telegram-bot-token', value: telegramBotToken }] : []
)
var appEnv = concat(
  [{ name: 'LOG_JSON', value: 'true' }],
  [
    { name: 'DATABASE_URL', value: databaseUrl }
    { name: 'DATABASE_ENTRA_AUTH', value: 'true' }
    { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId } // which identity DefaultAzureCredential uses
    // the model: no key, the managed identity signs in (role "Cognitive Services OpenAI User", main.bicep)
    { name: 'LLM_BASE_URL', value: '${ai.properties.endpoints['OpenAI Language Model Instance API']}openai/v1/' }
    { name: 'LLM_MODEL', value: modelName }
    // the dotties' computers: Container Apps Sandboxes in the group main.bicep created
    { name: 'SANDBOX_BACKEND', value: 'aca' }
    { name: 'AZURE_SUBSCRIPTION_ID', value: subscription().subscriptionId }
    { name: 'AZURE_RESOURCE_GROUP', value: resourceGroup().name }
    { name: 'SANDBOX_GROUP', value: 'sbg-${suffix}' }
    { name: 'SANDBOX_REGION', value: sandboxRegion }
    { name: 'USER_TIMEZONE', value: userTimezone }
    { name: 'SANDBOX_IDLE_SECONDS', value: string(sandboxIdleSeconds) }
    { name: 'SERVE', value: serve }
    { name: 'AGENT_MODE', value: agentMode }
  ],
  empty(gatewayUrl) ? [] : [{ name: 'GATEWAY_URL', value: gatewayUrl }],
  workosEnv,
  empty(secretsKey) ? [] : [{ name: 'SECRETS_KEY', secretRef: 'secrets-key' }],
  withTelegram ? [{ name: 'TELEGRAM_BOT_TOKEN', secretRef: 'telegram-bot-token' }] : []
)

resource app 'Microsoft.App/containerApps@2025-01-01' = {
  name: name
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    environmentId: env.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
        ipSecurityRestrictions: ipRules
      }
      registries: [{ server: acr.properties.loginServer, identity: identity.id }]
      secrets: secrets
    }
    template: {
      containers: [
        {
          name: 'app'
          image: image
          resources: serve == 'all' ? { cpu: json('1'), memory: '2Gi' } : { cpu: json('0.5'), memory: '1Gi' }
          env: appEnv
          // traffic only once the app answers: startup runs the migrations
          probes: [
            {
              type: 'Startup'
              httpGet: { path: '/api/health', port: 8000 }
              initialDelaySeconds: 2
              periodSeconds: 5
              failureThreshold: 12
            }
            {
              type: 'Readiness'
              httpGet: { path: '/api/health', port: 8000 }
              periodSeconds: 15
              failureThreshold: 3
            }
          ]
        }
      ]
      // Always on: the clock that fires schedules and the dispatcher that wakes dotties run in this process, so it must
      // not scale to zero. One replica; with more, an advisory lock in PostgreSQL keeps a single engine running.
      scale: { minReplicas: 1, maxReplicas: serve == 'all' ? 1 : 5 }
    }
  }
}

output fqdn string = app.properties.configuration.ingress.fqdn
