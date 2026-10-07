// A PostgreSQL Entra administrator. A module because the resource's name is the principal's object id, which for a
// managed identity is only known once the identity exists.
param serverName string
param objectId string
param principalName string
@allowed(['User', 'Group', 'ServicePrincipal'])
param principalType string

resource pg 'Microsoft.DBforPostgreSQL/flexibleServers@2025-08-01' existing = {
  name: serverName
}

resource admin 'Microsoft.DBforPostgreSQL/flexibleServers/administrators@2025-08-01' = {
  parent: pg
  name: objectId
  properties: { principalType: principalType, principalName: principalName, tenantId: tenant().tenantId }
}
