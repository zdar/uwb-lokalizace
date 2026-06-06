/*
 * WIFI SECRETS TEMPLATE - COPY THIS AS wifi_secrets.h
 * 
 * This is an example of how to configure your WiFi credentials.
 * Copy this content to src/wifi_secrets.h and fill in your details.
 * 
 * IMPORTANT: Never commit src/wifi_secrets.h to git!
 */

#ifndef WIFI_SECRETS_H
#define WIFI_SECRETS_H

// ===== ANL (Access Point) Mode Configuration =====
// This is the WiFi network created by the ANL (Anchor Node List) device
#define WIFI_AP_PASSWORD "rtlsnet12"        // Password for ANL AP
#define WIFI_AP_CHANNEL 6                   // WiFi channel for ANL AP
#define WIFI_AP_SSID_PREFIX "RTLS-NET-"     // Prefix for AP SSID (full SSID: RTLS-NET-<NETID>)

// ===== Home WiFi Configuration =====
// Set ENABLE_HOME_WIFI to 1 to use home WiFi, or 0 to disable
#define ENABLE_HOME_WIFI 0  // Set to 1 to enable home WiFi support

#if ENABLE_HOME_WIFI
    #define HOME_WIFI_SSID "your-home-wifi-ssid"      // Your home WiFi network name
    #define HOME_WIFI_PASSWORD "your-home-wifi-password"  // Your home WiFi password
#endif

// ===== OTA Configuration =====
#define OTA_PASSWORD "rtlsota12"            // Password for Over-The-Air updates

#endif // WIFI_SECRETS_H

/*
 * CONFIGURATION GUIDE
 * ===================
 * 
 * 1. HOME WIFI MODE (Optional):
 *    - Set ENABLE_HOME_WIFI to 1
 *    - Enter your home WiFi SSID and password
 *    - Nodes can be provisioned to use home WiFi instead of ANL network
 *    - This is useful for testing or deployment in your home network
 * 
 * 2. ANL MODE (Always Available):
 *    - Set ENABLE_HOME_WIFI to 0 if you only want ANL network
 *    - Or set to 1 but provision nodes to use ANL (default)
 *    - ANL mode creates a WiFi AP with SSID like: RTLS-NET-1234
 *    - Password is defined in WIFI_AP_PASSWORD
 * 
 * 3. PROVISIONING:
 *    - On startup, hold the button for 2+ seconds to enter provisioning menu
 *    - Stage 1: Select System Role (ANL or NODE)
 *    - Stage 2: 
 *      - If NODE with HOME_WIFI enabled: Choose WiFi source (HOME or ANL)
 *      - If ANL: Set Network ID (1000-9999)
 * 
 * 4. TYPICAL SCENARIOS:
 * 
 *    Scenario A - Home network only (no ANL):
 *    - ENABLE_HOME_WIFI = 0
 *    - Use provisioning to make one node ANL, others NODE
 *    - Nodes connect to your home WiFi automatically
 * 
 *    Scenario B - Flexible home and ANL network:
 *    - ENABLE_HOME_WIFI = 1
 *    - Configure home WiFi credentials
 *    - Use provisioning to toggle between HOME and ANL networks per node
 *    - Great for testing and portable deployments
 * 
 *    Scenario C - ANL network only (original behavior):
 *    - ENABLE_HOME_WIFI = 0
 *    - Use provisioning to set system roles and network ID as before
 * 
 * 5. CHANGING CREDENTIALS:
 *    - Edit wifi_secrets.h with new WiFi details
 *    - Recompile and upload (or use OTA)
 *    - Devices will use new credentials on next boot
 * 
 * 6. SECURITY:
 *    - wifi_secrets.h is in .gitignore (never committed)
 *    - Keep your credentials safe!
 *    - Use strong passwords
 *    - Consider changing OTA_PASSWORD from default
 */
