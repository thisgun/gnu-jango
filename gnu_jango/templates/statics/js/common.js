function IsReferredFromMe() {
  var ref = document.referrer;
  if (ref == null || ref.length == 0) {
    return false;
  }
  if (ref.indexOf("http://") == 0) {
    ref = ref.substring(7);
  }
  ref = ref.toLowerCase();

  var myDomain = document.domain;
  if (myDomain == null || myDomain.length == 0) {
    return false;
  }
  if (myDomain.indexOf("http://") == 0) {
    myDomain = myDomain.substring(7);
  }
  myDomain = myDomain.toLowerCase();

  return ref.indexOf(myDomain) == 0;
}

// 삭제 검사 확인
function del(href) {
  if (confirm("한번 삭제한 자료는 복구할 방법이 없습니다.\n\n정말 삭제하시겠습니까?")) {
    document.location.href = href;
  }
}

/**
 * 포인트 창
 **/
var win_point = function (href) {
  var new_win = window.open(href, "win_point", "left=100,top=100,width=600, height=600, scrollbars=1");
  new_win.focus();
};

/**
 * 쪽지 창
 **/
var win_memo = function (href) {
  var new_win = window.open(href, "win_memo", "left=100,top=100,width=620,height=500,scrollbars=1");
  new_win.focus();
};

/**
 * 스크랩 창
 **/
var win_scrap = function (href) {
  var new_win = window.open(href, "win_scrap", "left=100,top=100,width=600,height=600,scrollbars=1");
  new_win.focus();
};

// 쿠키 입력
function set_cookie(name, value, expirehours, domain) {
  var today = new Date();
  today.setTime(today.getTime() + 60 * 60 * 1000 * expirehours);
  document.cookie = name + "=" + escape(value) + "; path=/; expires=" + today.toGMTString() + ";";
  if (domain) {
    document.cookie += "domain=" + domain + ";";
  }
}

function get_cookie(name) {
  var cookieValue = null;
  if (document.cookie && document.cookie !== "") {
    var cookies = document.cookie.split(";");
    for (var i = 0; i < cookies.length; i += 1) {
      var cookie = jQuery.trim(cookies[i]);
      if (cookie.substring(0, name.length + 1) === name + "=") {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}

function csrf_safe_method(method) {
  return /^(GET|HEAD|OPTIONS|TRACE)$/.test(method);
}

jQuery(function ($) {
  $.ajaxSetup({
    beforeSend: function (xhr, settings) {
      var method = settings.type || settings.method || "GET";
      if (!csrf_safe_method(method) && !this.crossDomain) {
        var csrfToken = get_cookie("csrftoken");
        if (csrfToken) {
          xhr.setRequestHeader("X-CSRFToken", csrfToken);
        }
      }
    },
  });

  $(".win_point").click(function () {
    win_point(this.href);
    return false;
  });

  $(".win_memo").click(function () {
    win_memo(this.href);
    return false;
  });

  $(".win_scrap").click(function () {
    win_scrap(this.href);
    return false;
  });

  $(".win_password_lost").click(function () {
    win_password_lost(this.href);
    return false;
  });

  $(".win_coupon").click(function () {
    win_coupon(this.href);
    return false;
  });

  // 사이드뷰
  var sv_hide = false;
  $(".sv_member, .sv_guest").click(function () {
    $(".sv").removeClass("sv_on");
    $(this).closest(".sv_wrap").find(".sv").addClass("sv_on");
  });

  $(".sv, .sv_wrap").hover(
    function () {
      sv_hide = false;
    },
    function () {
      sv_hide = true;
    }
  );

  $(".sv_member, .sv_guest").focusin(function () {
    sv_hide = false;
    $(".sv").removeClass("sv_on");
    $(this).closest(".sv_wrap").find(".sv").addClass("sv_on");
  });

  $(".sv a").focusin(function () {
    sv_hide = false;
  });

  $(".sv a").focusout(function () {
    sv_hide = true;
  });

  // 셀렉트 ul
  var sel_hide = false;
  $(".sel_btn").click(function () {
    $(".sel_ul").removeClass("sel_on");
    $(this).siblings(".sel_ul").addClass("sel_on");
  });

  $(".sel_wrap").hover(
    function () {
      sel_hide = false;
    },
    function () {
      sel_hide = true;
    }
  );

  $(".sel_a").focusin(function () {
    sel_hide = false;
  });

  $(".sel_a").focusout(function () {
    sel_hide = true;
  });

  $(document).click(function () {
    if (sv_hide) {
      // 사이드뷰 해제
      $(".sv").removeClass("sv_on");
    }
    if (sel_hide) {
      // 셀렉트 ul 해제
      $(".sel_ul").removeClass("sel_on");
    }
  });

  $(document).focusin(function () {
    if (sv_hide) {
      // 사이드뷰 해제
      $(".sv").removeClass("sv_on");
    }
    if (sel_hide) {
      // 셀렉트 ul 해제
      $(".sel_ul").removeClass("sel_on");
    }
  });

  $(document).on("keyup change", "textarea#wr_content[maxlength]", function () {
    var str = $(this).val();
    var mx = parseInt($(this).attr("maxlength"));
    if (str.length > mx) {
      $(this).val(str.substr(0, mx));
      return false;
    }
  });
});
