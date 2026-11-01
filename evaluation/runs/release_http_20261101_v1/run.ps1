$ErrorActionPreference = 'Stop'
$base = 'http://127.0.0.1:8002'
$a = @{ 'x-api-key' = 'example-alice-key-12345' }
$c = @{ 'x-api-key' = 'example-carol-key-12345' }
$d = @{ 'x-api-key' = 'other-dave-key-123456' }
$rows = [System.Collections.Generic.List[object]]::new()
function Probe($name, $headers, $prompt, $extra = @{}, $stream = $false) {
    $body = @{ prompt = $prompt }
    foreach ($key in $extra.Keys) { $body[$key] = $extra[$key] }
    $path = if ($stream) { '/v1/chat/stream' } else { '/v1/chat' }
    try {
        $response = Invoke-WebRequest ($base + $path) -UseBasicParsing -Method Post -Headers $headers -ContentType 'application/json' -Body ($body | ConvertTo-Json -Compress) -TimeoutSec 45
        if ($stream) {
            $meta = $null
            foreach ($line in ($response.Content -split "`n")) {
                if ($line -match '^data: \{"lookup_scope"') { $meta = ($line.Substring(6) | ConvertFrom-Json) }
            }
            $row = [ordered]@{case=$name;status=[int]$response.StatusCode;provider=$response.Headers['X-Provider'];complete=($response.Content -match 'data: \[DONE\]');error=($response.Content -match 'event: error');meta=$meta}
        } else {
            $r = $response.Content | ConvertFrom-Json
            $row = [ordered]@{case=$name;status=[int]$response.StatusCode;cache=$r.cache;provider=$r.provider;lookup_scope=$r.lookup_scope;storage_scope=$r.storage_scope;storage_outcome=$r.storage_outcome;scope_reason=$r.scope_reason;note=$r.note;candidate_count=$r.candidate_count;selected_rank=$r.selected_rank;similarity=$r.similarity;trace=$r.candidate_trace;provider_invoked=$r.provider_invoked;finish_reason=$r.finish_reason;latency_ms=$r.latency_ms;stage_latency_ms=$r.stage_latency_ms}
        }
    } catch {
        $row = [ordered]@{case=$name;status=[int]$_.Exception.Response.StatusCode;error=$_.Exception.Message}
    }
    $rows.Add($row)
}
Probe 'carol_fixture_paraphrase' $c 'Explain how Python decorators work.'
Probe 'alice_generated_complete' $a 'Explain Redis TTL expiration for cache entries.'
Probe 'carol_generated_paraphrase' $c 'How does Redis expire cached entries after their TTL?'
Probe 'different_org' $d 'Explain how Python decorators work.'
Probe 'unauthorized_workspace' $d 'Explain how Python decorators work.' @{cache_scope='workspace';workspace='engineering'}
Probe 'alice_private' $a 'Explain my Redis password.'
Probe 'carol_private_isolated' $c 'Explain my Redis password.'
Probe 'secret_no_store' $a 'password=SuperSecret123'
Probe 'changed_action' $c 'How do I remove a Python decorator?'
Probe 'changed_environment' $c 'How do Python decorators work in Java?'
Probe 'changed_version' $c 'How do Python decorators work in Python 2?'
Probe 'stream_complete' $a 'Explain Redis set operations.' @{} $true
Probe 'stream_exact_repeat' $a 'Explain Redis set operations.' @{} $true
$result = [ordered]@{kind='isolated_mock_semantic_http_not_answer_quality';source_revision='37dc7a7400c1811cbf501d596d3535286ce81e17';ready=(Invoke-RestMethod ($base + '/ready'));rows=$rows}
$result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath '.tmp/release_probe.json' -Encoding utf8
$rows | ForEach-Object { [pscustomobject]$_ } | Select-Object case,status,cache,provider,lookup_scope,storage_scope,storage_outcome,note,candidate_count,selected_rank,similarity,provider_invoked,finish_reason,complete,error | Format-Table -AutoSize
