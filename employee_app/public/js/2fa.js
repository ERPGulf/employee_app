// Copyright (c) 2026, ERPGulf.com
// ERPGulf two-factor sign-in screens: QR enrolment, code entry and expiry.
// Loaded by web_include_js.
// Works with employee_app/twofa.py. Does nothing on pages without the sign-in form.
(function () {
	// The sign-in page is served at /login and also at / for guests, so key on
	// core's login script (continue_otp_app) instead of the path.

	// Store links. Fill APP_STORE_URL once the iPhone app has its App Store ID.
	const PLAY_URL = "https://play.google.com/store/apps/details?id=com.bazim.claudioncheckin";
	const APP_STORE_URL = "";
	const LOGO = "/assets/employee_app/images/erpgulf-logo-white.png";
	const SHIELD =
		'<svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linejoin="round"><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/></svg>';
	const WARN = `
  <div class="eg-warn">
   <div class="eg-wicon">!</div>
   <div><h4>Two-factor sign-in is mandatory. Follow it strictly.</h4><p>Attacks that steal passwords have risen sharply. Never share your code or QR code with anyone. ERPGulf and your IT team will never ask for them.</p></div>
   <div class="eg-ar"><h4>التحقق بخطوتين إلزامي. التزم به بدقة.</h4><p>ازدادت مؤخرًا الهجمات التي تسرق كلمات المرور. لا تشارك الرمز أو رمز QR مع أي شخص، فلن تطلبهما منك ERPGulf ولا فريق تقنية المعلومات أبدًا.</p></div>
  </div>`;

	frappe.ready(function () {
		if (typeof window.continue_otp_app !== "function") return;
		const core_continue_otp_app = window.continue_otp_app;

		window.continue_otp_app = function (setup, qrcode) {
			if (qrcode && typeof qrcode === "object" && qrcode.svg) {
				core_continue_otp_app(true, null); // builds the core code form we submit through
				show_enrolment(qrcode);
			} else if (qrcode && typeof qrcode === "object" && qrcode.expired) {
				core_continue_otp_app(false, null);
				show_expired();
			} else if (setup) {
				core_continue_otp_app(true, null); // enrolled user: core code form, our screen
				show_code_entry();
			} else {
				core_continue_otp_app(setup, qrcode);
			}
		};
	});

	function esc(text) {
		return $("<div>").text(text == null ? "" : String(text)).html();
	}

	function show_expired() {
		show_screen(
			"eg-small",
			`
  <div class="eg-state">
   <div class="eg-state-icon eg-amber"><svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/></svg></div>
   <div class="eg-two">
    <div><h2>Setup time expired</h2><p>Your two-factor setup time has expired. Please contact your administrator to issue a new QR code. This is for your security.</p></div>
    <div class="eg-ar"><h2>انتهت مدة الإعداد</h2><p>انتهت مدة إعداد التحقق بخطوتين. يرجى التواصل مع مسؤول النظام لإصدار رمز QR جديد، وذلك حفاظًا على أمانك.</p></div>
   </div>
   <button class="eg-btn eg-again" type="button">Back to sign-in · العودة لتسجيل الدخول</button>
  </div>`
		);
	}

	function show_code_entry() {
		const user = $("#login_email").val() || "";
		const $root = show_screen(
			"eg-small",
			`
  <div class="eg-head">
   <div><h1>Confirm your sign-in</h1><p>${user ? esc(user) + " · " : ""}${esc(window.location.hostname)}</p></div>
   <div class="eg-shield">${SHIELD}</div>
   <div class="eg-ar"><h1>تأكيد تسجيل الدخول</h1><p>التحقق بخطوتين</p></div>
  </div>
  <div class="eg-two eg-howto">
   <div>
    <div class="eg-pick"><h4>Using the Employee App?</h4><p>Just tap <b>Allow</b> on your phone. No code to type.</p></div>
    <div class="eg-or"><span>OR</span></div>
    <p><b>Using Google or Microsoft Authenticator?</b> Open the app, find this site, and type the <b>6-digit code</b> below. The code changes every 30 seconds.</p>
   </div>
   <div class="eg-ar">
    <div class="eg-pick"><h4>تستخدم تطبيق الموظفين؟</h4><p>اضغط <b>سماح</b> على هاتفك فقط، دون إدخال أي رمز.</p></div>
    <div class="eg-or"><span>أو</span></div>
    <p><b>تستخدم Google Authenticator أو Microsoft Authenticator؟</b> افتح التطبيق، وابحث عن هذا الموقع، واكتب <b>الرمز المكوّن من 6 أرقام</b> أدناه. يتغيّر الرمز كل 30 ثانية.</p>
   </div>
  </div>
  <div class="eg-entry">${code_form()}</div>
  <div class="eg-two eg-help">
   <p>Lost or changed your phone? Contact your administrator to reset your two-factor sign-in.</p>
   <p class="eg-ar">فقدت هاتفك أو غيّرته؟ تواصل مع مسؤول النظام لإعادة تعيين التحقق بخطوتين.</p>
  </div>
  ${WARN}`
		);
		wire_code_form($root);
	}

	// Overlay shell: ERPGulf logo on navy, one white card
	function show_screen(size, inner) {
		$("#eg-enrol").remove();
		add_styles();
		$("body").append(
			`<div id="eg-enrol" role="dialog" aria-modal="true"><div class="eg-top"><img src="${LOGO}" alt="ERPGulf"></div><div class="eg-card ${size}">${inner}</div></div>`
		);
		const $root = $("#eg-enrol");
		$root.find(".eg-again").on("click", () => window.location.reload());
		return $root;
	}

	function code_form() {
		return `
    <label class="eg-label" for="eg-code"><span>6-digit code</span><span>الرمز المكوّن من 6 أرقام</span></label>
    <input id="eg-code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="••••••">
    <div class="eg-error" role="alert"></div>
    <button id="eg-verify" class="eg-btn" type="button">Verify · تحقق</button>`;
	}

	const MSG = {
		short: ["Enter all 6 digits.", "أدخل الأرقام الستة كاملة."],
		wrong: [
			"That code is not correct. Make sure it is the code for this site and that your phone's time is set automatically, then try again.",
			"الرمز غير صحيح. تأكد من أنه رمز هذا الموقع وأن وقت هاتفك مضبوط تلقائيًا، ثم حاول مرة أخرى.",
		],
		busy: [
			"Too many attempts. Please wait a few minutes and try again.",
			"محاولات كثيرة جدًا. يرجى الانتظار بضع دقائق ثم المحاولة مرة أخرى.",
		],
		session: [
			"Your sign-in session timed out. Please sign in again.",
			"انتهت مهلة جلسة تسجيل الدخول. يرجى تسجيل الدخول مرة أخرى.",
		],
	};

	function show_error($root, msg, again) {
		$root
			.find(".eg-error")
			.html(
				`<div>${msg[0]}</div><div class="eg-ar">${msg[1]}</div>` +
				(again ? '<button class="eg-btn eg-again" type="button">Sign in again · تسجيل الدخول مجددًا</button>' : "")
			)
			.addClass("eg-show")
			.find(".eg-again")
			.on("click", () => window.location.reload());
	}

	// Verify through core's own form, so core's handlers sign the user in
	function wire_code_form($root) {
		const $code = $root.find("#eg-code");
		const $btn = $root.find("#eg-verify");
		const submit = () => {
			if ($btn.prop("disabled")) return;
			const code = digits($code.val());
			if (code.length !== 6) {
				show_error($root, MSG.short);
				$code.trigger("focus");
				return;
			}
			$root.find(".eg-error").removeClass("eg-show").empty();
			$btn.prop("disabled", true).addClass("eg-busy");
			$("#login_token").val(code);
			$(document).one("ajaxComplete", function (event, xhr) {
				if (xhr.status === 200) return; // core signs in and redirects
				$btn.prop("disabled", false).removeClass("eg-busy");
				$code.val("").trigger("focus");
				if (xhr.status === 401 || xhr.status === 403) show_error($root, MSG.wrong);
				else if (xhr.status === 429) show_error($root, MSG.busy);
				else show_error($root, MSG.session, true);
			});
			$(".form-verify").trigger("submit");
		};
		$btn.on("click", submit);
		$code.on("keydown", (e) => {
			if (e.key === "Enter") {
				e.preventDefault();
				submit();
			}
		});
		$code.on("input", () => $code.val(digits($code.val()).slice(0, 6)));
		$code.trigger("focus");
	}

	// Keeps digits only, and turns Arabic-Indic and Persian digits into 0-9
	function digits(text) {
		return String(text || "")
			.replace(/[\u0660-\u0669]/g, (d) => String(d.charCodeAt(0) - 0x0660))
			.replace(/[\u06F0-\u06F9]/g, (d) => String(d.charCodeAt(0) - 0x06f0))
			.replace(/\D/g, "");
	}

	function mmss(seconds) {
		const m = Math.floor(seconds / 60);
		const s = seconds % 60;
		return m + ":" + (s < 10 ? "0" : "") + s;
	}

	function store_badges() {
		const apple =
			'<svg width="20" height="24" viewBox="0 0 22 26" fill="#fff"><path d="M18.2 13.8c0-3 2.5-4.5 2.6-4.6-1.4-2.1-3.6-2.4-4.4-2.4-1.9-.2-3.6 1.1-4.6 1.1-.9 0-2.4-1.1-4-1-2 0-3.9 1.2-5 3-2.1 3.7-.5 9.2 1.5 12.2 1 1.5 2.2 3.1 3.8 3 1.5-.1 2.1-1 3.9-1s2.4 1 4 1c1.6 0 2.7-1.5 3.7-3 1.2-1.7 1.6-3.3 1.7-3.4-.1 0-3.2-1.2-3.2-4.9zM15.2 4.9c.8-1 1.4-2.4 1.2-3.9-1.2.1-2.7.8-3.5 1.8-.8.9-1.5 2.3-1.3 3.7 1.4.1 2.8-.7 3.6-1.6z"/></svg>';
		const play =
			'<svg width="20" height="22" viewBox="0 0 22 24"><path d="M1 1l11 11L1 23c-.4-.3-.6-.8-.6-1.4V2.4C.4 1.8.6 1.3 1 1z" fill="#00D7FE"/><path d="M15.7 8.3L12 12 1 1c.3-.2.8-.3 1.3 0z" fill="#00F076"/><path d="M15.7 15.7L2.3 23c-.5.3-1 .2-1.3 0l11-11z" fill="#FF3A44"/><path d="M20.3 10.8c1 .6 1 1.8 0 2.4l-4.6 2.5L12 12l3.7-3.7z" fill="#FFD400"/></svg>';
		const badge = (url, icon, small, big) =>
			(url ? `<a class="eg-store" href="${url}" target="_blank" rel="noopener">` : '<span class="eg-store">') +
			`${icon}<span><small>${small}</small><b>${big}</b></span>` +
			(url ? "</a>" : "</span>");
		return (
			'<div class="eg-stores">' +
			badge(APP_STORE_URL, apple, "Download on the", "App Store") +
			badge(PLAY_URL, play, "GET IT ON", "Google Play") +
			"</div>"
		);
	}

	function show_enrolment(qr) {
		const $root = show_screen(
			"",
			`
  <div class="eg-head">
   <div><h1>Set up two-factor sign-in</h1><p>${esc(qr.user)} · one-time setup for this account</p></div>
   <div class="eg-shield">${SHIELD}</div>
   <div class="eg-ar"><h1>إعداد التحقق بخطوتين</h1><p>إعداد لمرة واحدة لهذا الحساب</p></div>
  </div>

  <div class="eg-exp">
   <div>This setup page expires in <b class="eg-left"></b>. If it expires, please contact your administrator to issue a new QR code. This is for your security.</div>
   <div class="eg-clock"><span class="eg-left"></span></div>
   <div class="eg-ar">تنتهي صلاحية صفحة الإعداد خلال <b class="eg-left"></b>. إذا انتهت الصلاحية، يرجى التواصل مع مسؤول النظام لإصدار رمز QR جديد، وذلك حفاظًا على أمانك.</div>
  </div>

  <div class="eg-main">
   <div class="eg-col eg-en">
    <div class="eg-step"><i>1</i><div><h3>Install one app on your phone</h3>
     <div class="eg-pick"><span class="eg-rec">Recommended</span>
      <h4>Employee App <small>(Claudion Checkin)</small></h4>
      <p>The easiest way. When you sign in, just tap <b>Allow</b> on your phone. No code to type. The app also comes with many other features: attendance, leave requests and more.</p>
      ${store_badges()}</div>
     <p class="eg-alt"><b>Or</b> use Google Authenticator or Microsoft Authenticator. With these, you type the 6-digit code by hand each time you sign in.</p>
     <p class="eg-one">You need only one of these apps, not both.</p></div></div>
    <div class="eg-step"><i>2</i><div><h3>Scan the QR code</h3><p>Open the app you chose, tap <b>+</b>, and point the camera at the code in the middle of this page.</p></div></div>
    <div class="eg-step"><i>3</i><div><h3>Enter the 6-digit code</h3><p>Type the code the app shows and press <b>Verify</b> to finish setup.</p></div></div>
   </div>

   <div class="eg-mid">
    <div class="eg-qr"><img alt="QR code" src="data:image/svg+xml;base64,${qr.svg}"><div class="eg-qr-gone">Expired. Contact your administrator.<br>انتهت الصلاحية. تواصل مع المسؤول.</div></div>
    <div class="eg-acct">Account<b>${esc(qr.user)}</b></div>
    ${code_form()}
    <p class="eg-note">Finish within 3 minutes of signing in. If it times out, sign in again: this QR code stays the same until the setup page expires.</p>
    <p class="eg-note eg-ar">أكمل الخطوات خلال 3 دقائق من تسجيل الدخول. إذا انتهت المهلة، سجّل الدخول مرة أخرى، فرمز QR هذا لا يتغير حتى تنتهي صلاحية صفحة الإعداد.</p>
   </div>

   <div class="eg-col eg-ar">
    <div class="eg-step"><i>١</i><div><h3>ثبّت تطبيقًا واحدًا على هاتفك</h3>
     <div class="eg-pick"><span class="eg-rec">موصى به</span>
      <h4>تطبيق الموظفين <small>(Claudion Checkin)</small></h4>
      <p>الطريقة الأسهل: عند تسجيل الدخول، اضغط <b>سماح</b> على هاتفك فقط، دون إدخال أي رمز. ويأتي التطبيق أيضًا بميزات أخرى كثيرة، منها الحضور وطلبات الإجازة وغيرها.</p>
      ${store_badges()}</div>
     <p class="eg-alt"><b>أو</b> استخدم Google Authenticator أو Microsoft Authenticator، وفيهما تُدخل الرمز المكوّن من 6 أرقام يدويًا في كل مرة تسجّل فيها الدخول.</p>
     <p class="eg-one">تحتاج إلى تطبيق واحد فقط من هذه التطبيقات، وليس كليهما.</p></div></div>
    <div class="eg-step"><i>٢</i><div><h3>امسح رمز QR</h3><p>افتح التطبيق الذي اخترته، واضغط <b>+</b>، ثم وجّه الكاميرا نحو الرمز في منتصف هذه الصفحة.</p></div></div>
    <div class="eg-step"><i>٣</i><div><h3>أدخل الرمز المكوّن من 6 أرقام</h3><p>اكتب الرمز الظاهر في التطبيق واضغط <b>تحقق</b> لإكمال الإعداد.</p></div></div>
   </div>
  </div>

  ${WARN}`
		);

		// Countdown of the enrolment window
		let left = parseInt(qr.seconds_left, 10) || 0;
		const tick = () => {
			$root.find(".eg-left").text(mmss(Math.max(left, 0)));
			if (left <= 0) {
				$root.addClass("eg-expired");
				clearInterval(timer);
			}
			left -= 1;
		};
		const timer = setInterval(tick, 1000);
		tick();

		wire_code_form($root);
	}

	function add_styles() {
		if (document.getElementById("eg-enrol-css")) return;
		const css = `
#eg-enrol{position:fixed;inset:0;z-index:1050;overflow:auto;background:#1B2030;padding:24px 16px 40px;
 font-family:"Host Grotesk",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Noto Sans Arabic",Tahoma,sans-serif;color:#343A4A}
#eg-enrol:before{content:"";position:fixed;left:-180px;top:-200px;width:620px;height:620px;border-radius:50%;background:radial-gradient(circle,rgba(175,47,36,.55),transparent 65%);pointer-events:none}
#eg-enrol:after{content:"";position:fixed;right:-220px;bottom:-260px;width:700px;height:700px;border-radius:50%;background:radial-gradient(circle,rgba(99,32,95,.6),transparent 65%);pointer-events:none}
#eg-enrol *{box-sizing:border-box}
.eg-top{position:relative;z-index:1;max-width:1240px;margin:0 auto 18px}
.eg-top img{height:40px}
.eg-card{position:relative;z-index:1;max-width:1240px;margin:0 auto;background:#fff;border-radius:24px;box-shadow:0 30px 80px rgba(0,0,0,.35);overflow:hidden}
.eg-head{display:grid;grid-template-columns:1fr auto 1fr;gap:16px;align-items:center;padding:26px 36px 20px;border-bottom:1px solid #E6E8EC}
.eg-head h1{font-size:27px;font-weight:700;color:#1B2030;margin:0}
.eg-head p{color:#6B7385;font-size:14px;margin:4px 0 0}
.eg-shield{width:62px;height:62px;border-radius:18px;display:grid;place-items:center;background:linear-gradient(140deg,#AF2F24,#63205F);box-shadow:0 10px 24px rgba(99,32,95,.35)}
.eg-ar{direction:rtl;text-align:right}
.eg-exp{display:grid;grid-template-columns:1fr auto 1fr;gap:20px;align-items:center;background:#FFF6E0;color:#7A5600;padding:12px 36px;font-size:14.5px;border-bottom:1px solid #F3E3B5}
.eg-clock{background:#fff;border:1.5px solid #F0D58A;border-radius:12px;padding:6px 16px;font-weight:800;font-size:22px;color:#8A6200;font-variant-numeric:tabular-nums}
.eg-main{display:grid;grid-template-columns:1fr 360px 1fr}
.eg-col{padding:26px 32px}
.eg-en{border-right:1px solid #E6E8EC}
.eg-main>.eg-ar{border-left:1px solid #E6E8EC}
.eg-step{display:flex;gap:14px;margin-bottom:22px}
.eg-step:last-child{margin-bottom:0}
.eg-step i{flex:none;width:36px;height:36px;border-radius:11px;background:#1B2030;color:#fff;display:grid;place-items:center;font-style:normal;font-weight:800}
.eg-step:first-child i{background:linear-gradient(140deg,#AF2F24,#63205F)}
.eg-step h3{font-size:17px;color:#1B2030;font-weight:700;margin:0}
.eg-step p{font-size:14px;margin:5px 0 0;line-height:1.55}
.eg-ar .eg-step p{line-height:1.75}
.eg-stores{display:flex;gap:10px;margin-top:12px;direction:ltr}
.eg-ar .eg-stores{justify-content:flex-end}
.eg-store{display:inline-flex;align-items:center;gap:8px;background:#000;color:#fff!important;border-radius:10px;height:44px;padding:0 13px 0 10px;text-decoration:none!important}
.eg-store small{display:block;font-size:9.5px;line-height:1;opacity:.85}
.eg-store b{display:block;font-size:15.5px;line-height:1.2;font-weight:600}
.eg-pick{margin-top:10px;border:1.5px solid #F1CFCB;background:linear-gradient(135deg,#FFF7F6,#FBF3F8);border-radius:14px;padding:14px 16px}
.eg-pick h4{margin:6px 0 0;font-size:16px;font-weight:700;color:#1B2030}
.eg-pick h4 small{font-weight:500;color:#6B7385;font-size:12.5px}
.eg-rec{display:inline-block;background:linear-gradient(140deg,#AF2F24,#63205F);color:#fff;font-size:11px;font-weight:700;letter-spacing:.3px;padding:3px 9px;border-radius:20px}
.eg-alt{color:#6B7385;font-size:12.5px!important;margin-top:12px!important}
.eg-alt b{color:#343A4A}
.eg-one{font-size:12.5px!important;font-weight:600;color:#8A6200;margin-top:6px!important}
.eg-mid{background:linear-gradient(180deg,#FAFAFC,#F4F5F7);padding:26px 30px;text-align:center}
.eg-qr{position:relative;width:236px;height:236px;margin:0 auto;background:#fff;border-radius:20px;padding:16px;border:1px solid #E6E8EC;box-shadow:0 10px 30px rgba(27,32,48,.12)}
.eg-qr img{width:100%;height:100%;image-rendering:pixelated}
.eg-qr-gone{display:none;position:absolute;inset:0;border-radius:20px;background:rgba(255,255,255,.94);place-items:center;text-align:center;padding:16px;font-weight:700;color:#BF2D22;line-height:1.6}
.eg-expired .eg-qr img{filter:blur(6px)}
.eg-expired .eg-qr-gone{display:grid}
.eg-acct{margin-top:14px;font-size:13.5px;color:#6B7385}
.eg-acct b{display:block;color:#1B2030;font-size:15px;margin-top:2px;word-break:break-all}
.eg-label{display:flex;justify-content:space-between;margin:18px 0 8px;font-size:12.5px;font-weight:600;color:#1B2030}
#eg-code{width:100%;height:54px;border:1.5px solid #E6E8EC;border-radius:12px;text-align:center;font-size:26px;font-weight:700;letter-spacing:10px;color:#1B2030;outline:none;background:#fff}
#eg-code:focus{border-color:#D9372B;box-shadow:0 0 0 3px rgba(217,55,43,.15)}
.eg-btn{margin-top:12px;width:100%;min-height:50px;border:0;border-radius:12px;background:#D9372B;color:#fff;font-weight:700;font-size:16px;cursor:pointer;box-shadow:0 8px 18px rgba(217,55,43,.3)}
.eg-btn:hover{background:#BF2D22}
.eg-btn.eg-busy{opacity:.6;cursor:wait}
.eg-error{display:none;margin-top:12px;background:#FBEAE8;border:1px solid #F1CFCB;color:#9E2A20;border-radius:12px;padding:10px 14px;font-size:13.5px;line-height:1.55;text-align:left}
.eg-error.eg-show{display:block}
.eg-error .eg-ar{margin-top:4px}
.eg-error .eg-again{min-height:42px;font-size:14.5px;margin-top:10px}
.eg-card.eg-small{max-width:820px}
.eg-two{display:grid;grid-template-columns:1fr 1fr;gap:28px}
.eg-howto{padding:24px 36px 6px}
.eg-howto .eg-step{margin-bottom:14px}
.eg-howto .eg-step i{width:30px;height:30px;border-radius:9px;font-size:14px}
.eg-howto .eg-step p{margin:3px 0 0}
.eg-howto>div>p{font-size:14px;line-height:1.6;margin:0}
.eg-howto .eg-pick{margin:0}
.eg-howto .eg-pick h4{margin:0}
.eg-howto .eg-pick p{font-size:14px;margin:4px 0 0}
.eg-or{display:flex;align-items:center;gap:10px;margin:14px 0;color:#6B7385;font-size:12px;font-weight:700;letter-spacing:.5px}
.eg-or:before,.eg-or:after{content:"";flex:1;height:1px;background:#E6E8EC}
.eg-entry{max-width:380px;margin:4px auto 0;padding:0 20px 24px;text-align:center}
.eg-help{padding:14px 36px;border-top:1px solid #E6E8EC;font-size:13.5px;color:#4A5163;background:#FAFAFC}
.eg-help p{margin:0}
.eg-state{padding:56px 40px 36px;text-align:center}
.eg-state-icon{width:84px;height:84px;border-radius:50%;display:grid;place-items:center;margin:0 auto 22px}
.eg-amber{background:radial-gradient(circle,#F2B830,#E6A700);box-shadow:0 0 0 12px #FFF4D6,0 0 0 24px #FFFAEB}
.eg-state h2{font-size:22px;font-weight:700;color:#1B2030;margin:0}
.eg-state p{font-size:14.5px;color:#4A5163;margin:8px 0 0;line-height:1.6}
.eg-state .eg-two{text-align:left;margin-bottom:22px}
.eg-state .eg-ar{text-align:right}
.eg-state .eg-btn{max-width:380px}
.eg-note{font-size:12px;color:#6B7385;margin:10px 0 0;line-height:1.5}
.eg-warn{display:grid;grid-template-columns:auto 1fr 1fr;gap:24px;align-items:center;background:linear-gradient(90deg,#FBEAE8,#F6E6F0);border-top:1px solid #F1CFCB;padding:20px 36px}
.eg-wicon{width:50px;height:50px;border-radius:15px;background:#D9372B;color:#fff;display:grid;place-items:center;font-size:26px;font-weight:800}
.eg-warn h4{font-size:15.5px;color:#BF2D22;font-weight:800;margin:0}
.eg-warn p{font-size:13.5px;color:#5A2A2A;margin:4px 0 0;line-height:1.55}
@media (max-width:980px){
 .eg-head,.eg-exp,.eg-warn,.eg-two{grid-template-columns:1fr}
 .eg-shield,.eg-clock,.eg-wicon{justify-self:center}
 .eg-main{grid-template-columns:1fr}
 .eg-mid{order:-1}
 .eg-en,.eg-main>.eg-ar{border:0;border-top:1px solid #E6E8EC}
}`;
		$("<style id='eg-enrol-css'>").text(css).appendTo("head");
	}
})();
