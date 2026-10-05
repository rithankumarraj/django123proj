# Google sign-in setup

Google sign-in is disabled until OAuth credentials and the one permitted admin email are configured in the environment.

1. In Google Cloud Console, create or select a project.
2. Configure the OAuth consent screen. For testing, add the permitted Google account as a test user.
3. Create an OAuth client ID of type **Web application**.
4. Add these authorized redirect URIs for local development:
   - `http://127.0.0.1:8000/accounts/google/login/callback/`
   - `http://localhost:8000/accounts/google/login/callback/`
5. Set the environment variables in the same terminal used to start Django. Use the exact email address of the one Google account that should have admin access:

   ```sh
   export GOOGLE_CLIENT_ID='your-client-id'
   export GOOGLE_CLIENT_SECRET='your-client-secret'
   export GOOGLE_ADMIN_EMAIL='admin@gmail.com'
   ../venv/bin/python manage.py runserver 127.0.0.1:8000
   ```

The client secret must remain private and must not be committed to source control. Restart Django after changing these values. The **Continue with Google** button only appears when all three variables are set. Google sign-in creates or links an account only for the configured email when Google confirms the address is verified; that account receives staff access. Other Google accounts cannot access the admin dashboard.

For a temporary public tunnel, also add that tunnel's exact callback URL in Google Cloud Console. Quick-tunnel addresses can change, so their redirect URI must be updated whenever the address changes. Google OAuth redirects require an authorized domain and valid OAuth consent configuration; local development may be easier to test first using one of the localhost redirect URIs above.
