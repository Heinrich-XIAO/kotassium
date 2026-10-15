// Kotassium for macOS — loopback server + all on-device lanes, no dependencies.
// Cross-compiled from Linux: GOOS=darwin GOARCH=arm64 go build
package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"
)

const UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"

var (
	scCid   string
	cidOnce sync.Once
	libDir  string
	client  = &http.Client{Timeout: 30 * time.Second}
)

func httpBody(method, url string, body string) (int, string, error) {
	var rd io.Reader
	if body != "" {
		rd = strings.NewReader(body)
	}
	req, err := http.NewRequest(method, url, rd)
	if err != nil {
		return 0, "", err
	}
	req.Header.Set("User-Agent", UA)
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := client.Do(req)
	if err != nil {
		return 0, "", err
	}
	defer resp.Body.Close()
	b, err := io.ReadAll(resp.Body)
	return resp.StatusCode, string(b), err
}

func follow(method, url string, body string) (int, string, error) {
	for hops := 0; hops < 5; hops++ {
		code, text, err := httpBody(method, url, body)
		if err != nil {
			return code, text, err
		}
		if code == 301 || code == 302 {
			continue
		}
		return code, text, nil
	}
	return 0, "", fmt.Errorf("too many redirects")
}

func norm(s string) string {
	var b strings.Builder
	last := byte(' ')
	for _, c := range strings.ToLower(s) {
		if (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') {
			b.WriteRune(c)
			last = 'x'
		} else if last != ' ' {
			b.WriteByte(' ')
			last = ' '
		}
	}
	return strings.TrimSpace(b.String())
}

// ---- SoundCloud ----

var knownCids = []string{"vI5BsvpTIlavDLl7RDbbcFAPg8kls8Bg"}

func scClientID() (string, error) {
	if scCid != "" {
		return scCid, nil
	}
	for _, cid := range knownCids {
		code, _, err := httpBody("GET", "https://api-v2.soundcloud.com/search/tracks?q=test&client_id="+cid+"&limit=1", "")
		if err == nil && code == 200 {
			scCid = cid
			return scCid, nil
		}
	}
	_, home, err := follow("GET", "https://soundcloud.com/", "")
	if err != nil {
		return "", err
	}
	re := regexp.MustCompile(`https://a-v2\.sndcdn\.com/assets/[^"]+\.js`)
	for _, u := range re.FindAllString(home, -1) {
		_, js, err := follow("GET", u, "")
		if err != nil {
			continue
		}
		re2 := regexp.MustCompile(`client_id":"([a-zA-Z0-9]{28,40})"`)
		if m := re2.FindStringSubmatch(js); m != nil {
			scCid = m[1]
			return scCid, nil
		}
	}
	return "", fmt.Errorf("no soundcloud client_id found")
}

func scSearch(q string) (string, error) {
	cid, err := scClientID()
	if err != nil {
		return "", err
	}
	_, body, err := follow("GET", "https://api-v2.soundcloud.com/search/tracks?q="+url.QueryEscape(q)+"&client_id="+cid+"&limit=8", "")
	if err != nil {
		return "", err
	}
	var d struct {
		Collection []struct {
			ID       int    `json:"id"`
			Title    string `json:"title"`
			Duration int64  `json:"duration"`
			User     struct {
				Username string `json:"username"`
			} `json:"user"`
		} `json:"collection"`
	}
	if err := json.Unmarshal([]byte(body), &d); err != nil {
		return "", err
	}
	out := []map[string]interface{}{}
	for _, t := range d.Collection {
		out = append(out, map[string]interface{}{"source": "soundcloud", "title": t.Title,
			"artist": t.User.Username, "dur": t.Duration / 1000, "id": fmt.Sprint(t.ID), "full": true})
	}
	j, _ := json.Marshal(map[string]interface{}{"results": out})
	return string(j), nil
}

func scResolve(id string) (string, error) {
	cid, err := scClientID()
	if err != nil {
		return "", err
	}
	_, body, err := follow("GET", "https://api-v2.soundcloud.com/tracks/"+id+"?client_id="+cid, "")
	if err != nil {
		return "", err
	}
	var t struct {
		Media struct {
			Transcodings []struct {
				Format struct {
					Protocol string `json:"protocol"`
					Name     string `json:"name"`
				} `json:"format"`
				URL string `json:"url"`
			} `json:"transcodings"`
		} `json:"media"`
	}
	if err := json.Unmarshal([]byte(body), &t); err != nil {
		return "", err
	}
	for _, tr := range t.Media.Transcodings {
		if strings.Contains(tr.Format.Protocol, "progressive") {
			_, inner, err := follow("GET", tr.URL+"?client_id="+cid, "")
			if err != nil {
				return "", err
			}
			var u struct {
				URL string `json:"url"`
			}
			if err := json.Unmarshal([]byte(inner), &u); err != nil {
				return "", err
			}
			return u.URL, nil
		}
	}
	return "", fmt.Errorf("hls only (unsupported)")
}

// ---- Deezer ----

func dzSearch(q string) (string, error) {
	_, body, err := follow("GET", "https://api.deezer.com/search?q="+url.QueryEscape(q)+"&limit=8", "")
	if err != nil {
		return "", err
	}
	var d struct {
		Data []struct {
			ID       int    `json:"id"`
			Title    string `json:"title"`
			Duration int    `json:"duration"`
			Preview  string `json:"preview"`
			Artist   struct {
				Name string `json:"name"`
			} `json:"artist"`
			Album struct {
				Cover string `json:"cover"`
			} `json:"album"`
		} `json:"data"`
	}
	if err := json.Unmarshal([]byte(body), &d); err != nil {
		return "", err
	}
	out := []map[string]interface{}{}
	for _, t := range d.Data {
		out = append(out, map[string]interface{}{"source": "deezer", "title": t.Title,
			"artist": t.Artist.Name, "dur": t.Duration, "id": fmt.Sprint(t.ID),
			"preview": t.Preview, "full": false, "cover": t.Album.Cover})
	}
	j, _ := json.Marshal(map[string]interface{}{"results": out})
	return string(j), nil
}

// ---- YouTube (search only; playback via embed) ----

func ytSearch(q string) (string, error) {
	body := `{"context":{"client":{"clientName":"WEB","clientVersion":"2.20241126.01.00","hl":"en","gl":"US"}},"query":` + jsq(q) + `}`
	_, raw, err := follow("POST", "https://www.youtube.com/youtubei/v1/search?prettyPrint=false", body)
	if err != nil {
		return "", err
	}
	var d map[string]interface{}
	if err := json.Unmarshal([]byte(raw), &d); err != nil {
		return "", err
	}
	out := []map[string]interface{}{}
	var walk func(m map[string]interface{})
	walk = func(m map[string]interface{}) {
		if vr, ok := m["videoRenderer"].(map[string]interface{}); ok {
			title := ""
			if tr, ok := vr["title"].(map[string]interface{}); ok {
				if runs, ok := tr["runs"].([]interface{}); ok && len(runs) > 0 {
					if r0, ok := runs[0].(map[string]interface{}); ok {
						title, _ = r0["text"].(string)
					}
				}
			}
			artist := ""
			if ot, ok := vr["ownerText"].(map[string]interface{}); ok {
				if runs, ok := ot["runs"].([]interface{}); ok && len(runs) > 0 {
					if r0, ok := runs[0].(map[string]interface{}); ok {
						artist, _ = r0["text"].(string)
					}
				}
			}
			id, _ := vr["videoId"].(string)
			out = append(out, map[string]interface{}{"source": "youtube", "title": title,
				"artist": artist, "dur": 0, "id": id, "full": false})
		}
		for _, v := range m {
			if sub, ok := v.(map[string]interface{}); ok {
				walk(sub)
			} else if arr, ok := v.([]interface{}); ok {
				for _, e := range arr {
					if sub, ok := e.(map[string]interface{}); ok {
						walk(sub)
					}
				}
			}
		}
	}
	walk(d)
	j, _ := json.Marshal(map[string]interface{}{"results": out[:min(len(out), 5)]})
	return string(j), nil
}

func jsq(s string) string { b, _ := json.Marshal(s); return string(b) }
func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

// ---- Internet Archive ----

func iaSearch(q string) (string, error) {
	_, body, err := follow("GET", "https://archive.org/advancedsearch.php?q="+url.QueryEscape(q+" AND mediatype:audio")+"&fl%5B%5D=identifier&fl%5B%5D=title&rows=8&output=json", "")
	if err != nil {
		return "", err
	}
	var d struct {
		Response struct {
			Docs []struct {
				Identifier string `json:"identifier"`
				Title      string `json:"title"`
			} `json:"docs"`
		} `json:"response"`
	}
	if err := json.Unmarshal([]byte(body), &d); err != nil {
		return "", err
	}
	out := []map[string]interface{}{}
	for _, t := range d.Response.Docs {
		out = append(out, map[string]interface{}{"source": "archive", "title": t.Title,
			"artist": "", "dur": 0, "id": t.Identifier, "full": true})
	}
	j, _ := json.Marshal(map[string]interface{}{"results": out})
	return string(j), nil
}

func dlFile(src, id, url string) (string, error) {
	path := filepath.Join(libDir, src+"_"+id+".mp3")
	if st, err := os.Stat(path); err == nil && st.Size() > 10000 {
		return path, nil
	}
	req, _ := http.NewRequest("GET", url, nil)
	req.Header.Set("User-Agent", UA)
	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return "", fmt.Errorf("download HTTP %d", resp.StatusCode)
	}
	f, err := os.Create(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	_, err = io.Copy(f, resp.Body)
	return path, err
}

func main() {
	home, _ := os.UserHomeDir()
	libDir = filepath.Join(home, "Music", "Kotassium")
	os.MkdirAll(libDir, 0755)

	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/", "/index.html":
			http.ServeFile(w, r, filepath.Join(home, "Music", "Kotassium", "index.html"))
		case "/api/search":
			q := r.URL.Query().Get("q")
			out := []map[string]interface{}{}
			if j, err := ytSearch(q); err == nil {
				var d struct {
					Results []map[string]interface{} `json:"results"`
				}
				json.Unmarshal([]byte(j), &d)
				out = append(out, d.Results...)
			}
			if j, err := dzSearch(q); err == nil {
				var d struct {
					Results []map[string]interface{} `json:"results"`
				}
				json.Unmarshal([]byte(j), &d)
				out = append(out, d.Results...)
			}
			if j, err := scSearch(q); err == nil {
				var d struct {
					Results []map[string]interface{} `json:"results"`
				}
				json.Unmarshal([]byte(j), &d)
				out = append(out, d.Results...)
			}
			if len(out) == 0 {
				if j, err := iaSearch(q); err == nil {
					var d struct {
						Results []map[string]interface{} `json:"results"`
					}
					json.Unmarshal([]byte(j), &d)
					out = append(out, d.Results...)
				}
			}
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(map[string]interface{}{"results": out})
		case "/api/download":
			src := r.URL.Query().Get("src")
			id := r.URL.Query().Get("id")
			var url string
			var err error
			switch src {
			case "soundcloud":
				url, err = scResolve(id)
			case "archive":
				url = "https://archive.org/download/" + id + "/" + id + "_vbr.mp3"
			case "deezer":
				url = r.URL.Query().Get("preview")
			default:
				http.Error(w, "source needs no download or is unsupported", 400)
				return
			}
			if err != nil {
				http.Error(w, err.Error(), 500)
				return
			}
			path, err := dlFile(src, id, url)
			if err != nil {
				http.Error(w, err.Error(), 500)
				return
			}
			w.Header().Set("Content-Disposition", `attachment; filename="`+filepath.Base(path)+`"`)
			http.ServeFile(w, r, path)
		case "/api/play":
			src := r.URL.Query().Get("src")
			id := r.URL.Query().Get("id")
			var url string
			var err error
			switch src {
			case "soundcloud":
				url, err = scResolve(id)
			case "archive":
				url = "https://archive.org/download/" + id + "/" + id + "_vbr.mp3"
			case "deezer":
				url = r.URL.Query().Get("preview")
			default:
				http.Error(w, "unsupported", 400)
				return
			}
			if err != nil {
				http.Error(w, err.Error(), 500)
				return
			}
			path, err := dlFile(src, id, url)
			if err != nil {
				http.Error(w, err.Error(), 500)
				return
			}
			http.ServeFile(w, r, path)
		case "/api/library":
			files, _ := filepath.Glob(filepath.Join(libDir, "*.mp3"))
			out := []string{}
			for _, f := range files {
				out = append(out, filepath.Base(f))
			}
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(map[string]interface{}{"library": out})
		case "/manifest.json":
			w.Header().Set("Content-Type", "application/manifest+json")
			fmt.Fprint(w, `{"name":"Kotassium","short_name":"Kotassium","start_url":"/","display":"standalone","background_color":"#191414","theme_color":"#191414"}`)
		default:
			http.NotFound(w, r)
		}
	})

	addr := "127.0.0.1:8420"
	url := "http://" + addr
	log := func(msg string) { fmt.Printf("[%s] %s\n", time.Now().Format("15:04:05"), msg) }
	log("Kotassium for macOS — library: " + libDir)
	if yt, err := exec.LookPath("yt-dlp"); err == nil {
		log("yt-dlp found: " + yt + " (youtube downloads enabled)")
	} else {
		log("yt-dlp not found - youtube tracks are stream-only (install it to enable downloads)")
	}
	log("opening " + url + " in your browser")
	if err := exec.Command("open", url).Start(); err != nil {
		log("open the URL manually in your browser")
	}
	log("Ctrl+C to quit")
	if err := http.ListenAndServe(addr, mux); err != nil {
		log("server error: " + err.Error())
		os.Exit(1)
	}
}
