#!/bin/bash

# set -x

# Keycloak server URL
# KEYCLOAK_URL="http://localhost:8030"
KEYCLOAK_URL=$1
# Realm name
REALM="master"
# Admin credentials
ADMIN_USER="admin"
ADMIN_PASSWORD="admin"
# Client details
CLIENT_ID="ticket-service"
# Redirect URIs for the client, modify as needed
REDIRECT_URIS='["*"]'

# Step 1: Obtain admin access token
TOKEN=$(curl -s -X POST "$KEYCLOAK_URL/realms/master/protocol/openid-connect/token" \
   -H "Content-Type: application/x-www-form-urlencoded" \
   -d "username=$ADMIN_USER" \
   -d "password=$ADMIN_PASSWORD" \
   -d "grant_type=password" \
   -d "client_id=admin-cli" | jq -r '.access_token')

if [ "$TOKEN" == "null" ]; then
    # echo "Failed to obtain access token"
    exit 1
fi

# echo "Access token obtained: $TOKEN"

# Step 2: Create a new client
_=$(curl -s -X POST "$KEYCLOAK_URL/admin/realms/$REALM/clients" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $TOKEN" \
    -d '{
        "clientId": "'$CLIENT_ID'", 
        "enabled": true, 
        "publicClient": false, 
        "redirectUris": '"$REDIRECT_URIS"', 
        "clientAuthenticatorType": "client-secret",
        "standardFlowEnabled": true,
        "implicitFlowEnabled": false,
        "directAccessGrantsEnabled": true,
        "serviceAccountsEnabled": true,
        "authorizationServicesEnabled": true
    }')

# Step 2: Get client uuid
CLIENT_UUID=$(curl -s -X GET "$KEYCLOAK_URL/admin/realms/$REALM/clients?clientId=$CLIENT_ID" \
    -H "Authorization: Bearer $TOKEN" | jq -r '.[0].id')

if [ "$CLIENT_UUID" == "null" ]; then
    # echo "Failed to create client or retrieve client UUID"
    exit 1
# else
    # echo "Client created successfully with UUID: $CLIENT_UUID"
fi

# Step 4: Get the client secret
CLIENT_SECRET=$(curl -s -X GET "$KEYCLOAK_URL/admin/realms/$REALM/clients/$CLIENT_UUID/client-secret" \
    -H "Authorization: Bearer $TOKEN" | jq -r '.value')

if [ "$CLIENT_SECRET" == "null" ]; then
    # echo "Failed to retrieve client secret"
    exit 1
fi

_=$(curl -s -X PUT "$KEYCLOAK_URL/admin/realms/$REALM" \
    -H 'Content-Type: application/json' \
    -H "Authorization: Bearer $TOKEN" \
    -d '{"accessTokenLifespan": 86400}')

echo $CLIENT_SECRET