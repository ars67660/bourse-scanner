# Configuration du portefeuille virtuel automatique

Cette fonctionnalité reste une **simulation** : elle ne se connecte à aucun courtier et n'envoie aucun ordre réel.

## 1. Créer le projet Supabase

1. Créez un compte sur https://supabase.com/ puis un nouveau projet.
2. Choisissez une région européenne (par exemple Paris, si proposée) et conservez le mot de passe de base de données dans votre gestionnaire de mots de passe.
3. Dans **SQL Editor**, ouvrez un nouvel onglet, collez le contenu de `supabase/virtual_portfolio.sql` et exécutez-le.
4. Dans **Project Settings > API** (ou **Connect** selon l'interface), récupérez :
   - l'URL du projet (`https://....supabase.co`) ;
   - la clé secrète `service_role` (ou la clé secrète serveur équivalente).

**Ne communiquez jamais la clé service_role dans une conversation, un ticket ou un commit Git.** Elle donne un accès privilégié à la base.

## 2. Ajouter les secrets GitHub

Dans le dépôt GitHub, ouvrez **Settings > Secrets and variables > Actions > New repository secret** et créez :

- `SUPABASE_URL` : URL du projet ;
- `SUPABASE_SERVICE_ROLE_KEY` : clé secrète serveur.

Pour que l'interface Streamlit lise le même portefeuille, ajoutez les mêmes valeurs dans les **Secrets** de l'application Streamlit sous les mêmes noms. N'ajoutez pas de fichier de secrets au dépôt.

## 3. Données et sécurité

- La table `virtual_portfolio` contient le solde, les positions ouvertes, l'historique et l'horodatage du dernier cycle.
- La table `virtual_cycle_runs` sert à tracer les exécutions et à empêcher les doublons.
- La sécurité RLS est activée sans accès public : les clés publiques/anon ne doivent pas être utilisées pour le moteur.
- L'insertion initiale est idempotente : elle ne réinitialise pas une ligne existante.
- Le portefeuille local `portefeuille_virtuel.json` ne doit pas être supprimé avant migration et vérification des données.

## 4. Activation

Le déclenchement planifié toutes les 15 minutes sera activé par GitHub Actions après ajout du moteur automatique partagé. GitHub Actions utilise une planification cron, qui peut être retardée et n'est pas une garantie d'exécution à la minute exacte.

Avant activation, il faudra migrer le portefeuille virtuel local existant vers Supabase et vérifier le solde, les positions et l'historique. Ne réinitialisez pas le portefeuille pour effectuer cette migration.
