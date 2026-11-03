# Portefeuille virtuel automatique sans base de données

Le portefeuille est conservé dans \`portefeuille_virtuel.json\` dans ce dépôt. GitHub Actions lance le moteur toutes les 15 minutes. La simulation n'envoie aucun ordre à un courtier.

## 1. Créer un jeton GitHub pour Streamlit

L'interface Streamlit doit lire et écrire le fichier JSON distant afin que les cycles manuels et automatiques partagent le même état.

1. Sur GitHub, ouvrez **Settings > Developer settings > Personal access tokens > Fine-grained tokens**.
2. Créez un jeton limité au dépôt \`ars67660/bourse-scanner\`.
3. Accordez uniquement **Contents: Read and write**.
4. Dans les paramètres/secrets de l'application Streamlit, ajoutez le jeton sous le nom \`GITHUB_TOKEN\`.

Ne collez jamais ce jeton dans le dépôt ou dans une conversation. Ne le mettez pas dans \`scanner_api_keys.json\`.

## 2. Migrer le portefeuille existant sans le perdre

1. Ouvrez l'application Streamlit actuellement déployée.
2. Ajoutez \`GITHUB_TOKEN\` dans ses secrets, puis redémarrez l'application.
3. À la première ouverture, si le fichier distant n'existe pas, l'application publie le portefeuille local existant dans le dépôt. Si aucun portefeuille local n'existe, elle initialise le capital virtuel à 10 000 €.
4. Vérifiez dans le dépôt que \`portefeuille_virtuel.json\` contient le bon solde, toutes les positions ouvertes et l'historique des clôtures.

Le worker programmé refuse volontairement de créer un portefeuille vide si le JSON manque : cela évite d'écraser silencieusement un portefeuille qui n'aurait pas encore été migré.

## 3. Activer GitHub Actions

Après fusion de la Pull Request :
- ouvrez l'onglet **Actions** et autorisez les workflows si GitHub le demande ;
- vérifiez que le workflow **Portefeuille virtuel automatique** est activé ;
- vérifiez que \`portefeuille_virtuel.json\` existe avant le premier cycle ;
- lancez une première exécution manuelle (*Run workflow*).

Le déclenchement cron est réglé sur toutes les 15 minutes. GitHub peut retarder les exécutions planifiées ; ce n'est pas une horloge temps réel.

## 4. Paramètres appliqués

- Maximum : 50 positions simultanées.
- Score minimum : 65/100.
- Risque théorique : 1 % de l'équité par cycle, partagé entre les nouvelles entrées.
- Aucune réserve minimale de liquidités : le cash disponible peut être engagé, dans les limites du budget de risque et du capital disponible.
- Les positions LONG et SHORT sont simulées.
- Une position est clôturée sur stop-loss, take-profit ou signal opposé confirmé.
- Horizon du moteur planifié : journalier (Yahoo Finance, données susceptibles d'être retardées).

## 5. Limites et précautions

Le JSON est un stockage léger, pas une base transactionnelle. La concurrence GitHub Actions est sérialisée, mais évitez de lancer plusieurs cycles manuels depuis des environnements différents au même moment. GitHub conserve l'historique du fichier dans les commits : ne mettez aucune donnée sensible dans ce JSON.

Aucun ordre réel, aucun compte de courtage et aucune clé de courtier ne sont utilisés.
