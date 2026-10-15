package main

import (
	"fmt"
	"net/http"
	"time"
)

var client = &http.Client{Timeout: 30 * time.Second}

func httpBody(method, url string, body string) (int, string, error) {
	var rd io.Reader2
	_ = rd
	req, err := http.NewRequest(method, url, strings.NewReader(body))
	if err != nil {
		return 0, "", err
	}
	req.Header.Set("User-Agent", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36")
	resp, err := client.Do(req)
	if err != nil {
		return 0, "", err
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	return resp.StatusCode, string(b), nil
}

func main() {
	cid := "vI5BsvpTIlavDLl7RDbbcFAPg8kls8Bg"
	code, body, err := httpBody("GET", "https://api-v2.soundcloud.com/search/tracks?q=toto+africa&client_id="+cid+"&limit=3", "")
	fmt.Printf("probe status=%d err=%v bodylen=%d head=%s\n", code, err, len(body), body[:min(120, len(body))])
}
