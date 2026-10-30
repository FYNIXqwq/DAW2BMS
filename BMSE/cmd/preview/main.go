// Local web harness: shares the real Go parser/serializer without exposing filesystem operations.
package main

import (
	"bmse/internal/chart"
	"encoding/base64"
	"encoding/json"
	"flag"
	"log"
	"net/http"
	"strings"
	"time"
)

func main() {
	addr := flag.String("addr", "127.0.0.1:9246", "loopback address")
	root := flag.String("root", "frontend/dist", "frontend directory")
	flag.Parse()
	mux := http.NewServeMux()
	mux.HandleFunc("/api/", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "POST" {
			http.Error(w, "POST required", 405)
			return
		}
		if origin := r.Header.Get("Origin"); origin != "" && origin != "http://"+r.Host {
			http.Error(w, "origin rejected", 403)
			return
		}
		r.Body = http.MaxBytesReader(w, r.Body, 128<<20)
		w.Header().Set("Content-Type", "application/json")
		var result any
		var e error
		switch strings.TrimPrefix(r.URL.Path, "/api/") {
		case "DecodeDocument":
			var args []string
			e = json.NewDecoder(r.Body).Decode(&args)
			if e == nil && len(args) == 2 {
				result, e = chart.DecodeDocument(args[0], args[1])
			} else {
				http.Error(w, "invalid arguments", 400)
				return
			}
		case "EncodeDocument":
			var d chart.Document
			e = json.NewDecoder(r.Body).Decode(&d)
			if e == nil {
				result, e = chart.EncodeDocument(d)
			}
		case "Branches":
			var text string
			e = json.NewDecoder(r.Body).Decode(&text)
			if e == nil {
				result = chart.Branches(text)
			}
		case "ResolveBranches":
			var args []json.RawMessage
			e = json.NewDecoder(r.Body).Decode(&args)
			if e == nil && len(args) == 2 {
				var text string
				var choices map[int]int
				e = json.Unmarshal(args[0], &text)
				if e == nil {
					e = json.Unmarshal(args[1], &choices)
				}
				if e == nil {
					result, e = chart.ResolveBranches(text, choices)
				}
			} else {
				http.Error(w, "invalid arguments", 400)
				return
			}
		case "ImportIBMSC":
			var args []json.RawMessage
			e = json.NewDecoder(r.Body).Decode(&args)
			if e == nil && len(args) == 2 {
				var data string
				var extended bool
				e = json.Unmarshal(args[0], &data)
				if e == nil {
					e = json.Unmarshal(args[1], &extended)
				}
				if e == nil {
					var b []byte
					b, e = base64.StdEncoding.DecodeString(data)
					if e == nil {
						result, e = chart.ParseIBMSC(b, extended)
					}
				}
			} else {
				http.Error(w, "invalid arguments", 400)
				return
			}
		case "Parse":
			var text string
			e = json.NewDecoder(r.Body).Decode(&text)
			if e == nil {
				result, e = chart.Parse(text)
			}
		case "Serialize", "Validate":
			var d chart.Document
			e = json.NewDecoder(r.Body).Decode(&d)
			if e == nil {
				if strings.HasSuffix(r.URL.Path, "Serialize") {
					result, e = chart.Serialize(d)
				} else {
					result = chart.Validate(d)
				}
			}
		default:
			http.NotFound(w, r)
			return
		}
		if e != nil {
			w.WriteHeader(400)
			_ = json.NewEncoder(w).Encode(map[string]string{"error": e.Error()})
			return
		}
		_ = json.NewEncoder(w).Encode(result)
	})
	mux.Handle("/", http.FileServer(http.Dir(*root)))
	s := &http.Server{Addr: *addr, Handler: mux, ReadHeaderTimeout: 5 * time.Second}
	log.Printf("BMSE web harness http://%s", *addr)
	log.Fatal(s.ListenAndServe())
}
