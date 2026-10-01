# ==============================================================================
# 🛡️ RajLabs FreeRADIUS & Wi-Fi AAA Diagnostic Suite for Windows (PowerShell)
# ==============================================================================
# Usage (One-Click from GitHub):
#   irm https://raw.githubusercontent.com/authoritydmc/freeradius-app/main/scripts/test-wifi-radius.ps1 | iex
#
# NO secrets or passwords are stored in this script.
# ==============================================================================

param(
    [string]$Server = "80.225.195.202",
    [int]$AuthPort = 1812,
    [int]$AcctPort = 1813,
    [string]$Secret = "",
    [string]$Username = "",
    [string]$Password = "",
    [string]$ApiUrl = "https://backend.rajlabs.in/radius"
)

Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "   🛡️ RajLabs FreeRADIUS Wi-Fi & AAA Diagnostic Client (Windows)" -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host " Target RADIUS Server : $Server:$AuthPort (UDP)"
Write-Host " Accounting Port      : $AcctPort (UDP)"
Write-Host " Web Portal & API     : $ApiUrl"
Write-Host "================================================================="
Write-Host ""

# Prompt for Secret if not supplied
if (-not $Secret) {
    $secPass = Read-Host "🔑 Enter RADIUS NAS Shared Secret" -AsSecureString
    $BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secPass)
    $Secret = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
}

if (-not $Username) {
    $Username = Read-Host "👤 Enter Username to test"
}

if (-not $Password) {
    $pwdSec = Read-Host "🔒 Enter Password for $Username" -AsSecureString
    $BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($pwdSec)
    $Password = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
}

# 1. Test Web API & Captive Portal
Write-Host ""
Write-Host "🔍 [1/2] Checking Web Portal & Health Endpoint..." -ForegroundColor Yellow
try {
    $resp = Invoke-RestMethod -Uri "$ApiUrl/api/health" -Method Get -TimeoutSec 5 -ErrorAction SilentlyContinue
    if ($resp.status -eq "healthy") {
        Write-Host "   ✅ Web Portal is LIVE and Healthy (HTTP 200) -> $ApiUrl" -ForegroundColor Green
    } else {
        Write-Host "   ⚠️  Web API responded: $($resp | ConvertTo-Json -Compress)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "   ⚠️  Could not reach $ApiUrl/api/health ($_)" -ForegroundColor DarkYellow
}

# 2. Test RADIUS Authentication via UDP
Write-Host ""
Write-Host "🔐 [2/2] Testing WPA2/WPA3-Enterprise 802.1X Authentication..." -ForegroundColor Yellow

function Send-RadiusPacket {
    param($HostName, $Port, $SharedSecret, $User, $Pass)

    $udp = New-Object System.Net.Sockets.UdpClient
    $udp.Client.ReceiveTimeout = 4000
    
    try {
        $reqId = [byte](Get-Random -Minimum 1 -Maximum 255)
        $authenticator = New-Object byte[] 16
        $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        $rng.GetBytes($authenticator)

        # Attribute 1: User-Name
        $userBytes = [System.Text.Encoding]::UTF8.GetBytes($User)
        $attrUser = @(1, ($userBytes.Length + 2)) + $userBytes

        # Attribute 2: User-Password (RFC 2865 MD5 XOR Obfuscation)
        $passBytes = [System.Text.Encoding]::UTF8.GetBytes($Pass)
        $paddedLen = [Math]::Ceiling($passBytes.Length / 16) * 16
        if ($paddedLen -eq 0) { $paddedLen = 16 }
        $passPadded = New-Object byte[] $paddedLen
        [Array]::Copy($passBytes, $passPadded, $passBytes.Length)

        $md5 = [System.Security.Cryptography.MD5]::Create()
        $secretBytes = [System.Text.Encoding]::UTF8.GetBytes($SharedSecret)
        
        $hashInput = $secretBytes + $authenticator
        $md5Hash = $md5.ComputeHash($hashInput)
        $encPass = New-Object byte[] $paddedLen

        for ($i = 0; $i -lt 16; $i++) {
            $encPass[$i] = $passPadded[$i] -bxor $md5Hash[$i]
        }

        for ($b = 16; $b -lt $paddedLen; $b += 16) {
            $prevBlock = $encPass[($b-16)..($b-1)]
            $hashInput = $secretBytes + $prevBlock
            $md5Hash = $md5.ComputeHash($hashInput)
            for ($i = 0; $i -lt 16; $i++) {
                $encPass[$b + $i] = $passPadded[$b + $i] -bxor $md5Hash[$i]
            }
        }

        $attrPass = @(2, ($encPass.Length + 2)) + $encPass
        $attrNas = @(4, 6, 127, 0, 0, 1)
        $attrPort = @(5, 6, 0, 0, 0, 0)
        $attrService = @(6, 6, 0, 0, 0, 2)

        $allAttrs = $attrUser + $attrPass + $attrNas + $attrPort + $attrService
        $packetLen = 20 + $allAttrs.Length
        $header = @(1, $reqId, [byte]($packetLen -shr 8), [byte]($packetLen -band 255)) + $authenticator
        $packet = $header + $allAttrs

        $udp.Send($packet, $packet.Length, $HostName, $Port) | Out-Null

        $endpoint = New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Any, 0)
        $response = $udp.Receive([ref]$endpoint)

        if ($response[0] -eq 2) {
            Write-Host "   🎉 SUCCESS: Received Access-Accept (Code 2) from $($endpoint.Address):$($endpoint.Port)!" -ForegroundColor Green
            Write-Host "   👤 Account '$User' is AUTHORIZED on RajLabs FreeRADIUS." -ForegroundColor Green
            return $true
        } elseif ($response[0] -eq 3) {
            Write-Host "   ❌ REJECTED: Received Access-Reject (Code 3) from $($endpoint.Address)." -ForegroundColor Red
            return $false
        } else {
            Write-Host "   ⚠️  Received RADIUS Packet Code $($response[0])." -ForegroundColor Yellow
            return $false
        }
    } catch {
        Write-Host "   ❌ UDP Timeout or error contacting $HostName`:$Port ($($_.Exception.Message))" -ForegroundColor Red
        return $false
    } finally {
        $udp.Close()
    }
}

Send-RadiusPacket -HostName $Server -Port $AuthPort -SharedSecret $Secret -User $Username -Pass $Password
