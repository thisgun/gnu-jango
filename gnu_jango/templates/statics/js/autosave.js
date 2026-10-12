// 임시 저장하는 시간을 초단위로 설정한다.
var AUTOSAVE_INTERVAL = 10; // 초

// 글의 제목과 내용을 바뀐 부분이 있는지 비교하기 위하여 저장해 놓는 변수
var save_wr_subject = null;
var save_wr_content = null;

if (typeof ajax_auto_save_url !== "undefined") {
  function autosave() {
    jQuery("form#fwrite").each(function () {
      if (gnu_editor != "") {
        if (typeof get_editor_wr_content == "function") {
          this.wr_content.value = get_editor_wr_content();
        }
      }

      // 변수에 저장해 놓은 값과 다를 경우에만 임시 저장함
      if (save_wr_subject != this.wr_subject.value || save_wr_content != this.wr_content.value) {
        jQuery.ajax({
          url: ajax_auto_save_url,
          data: {
            mode: "save",
            uid: this.uid.value,
            subject: this.wr_subject.value,
            content: this.wr_content.value,
            csrfmiddlewaretoken: this.csrfmiddlewaretoken.value,
          },
          type: "POST",
          datatype: "JSON",
          success: function (data) {
            if (data) {
              jQuery("#autosave_count").html(data.count);
            }
          },
        });
        save_wr_subject = this.wr_subject.value;
        save_wr_content = this.wr_content.value;
      }
    });
  }

  jQuery(function ($) {
    if (gnu_is_user) {
      setInterval(autosave, AUTOSAVE_INTERVAL * 1000);
    }

    var csrfmiddlewaretoken_val = $("form#fwrite").find("input[name=csrfmiddlewaretoken]").val();

    // 임시저장된 글목록을 가져옴
    $("#btn_autosave").click(function (e) {
      console.log(e);
      console.log(csrfmiddlewaretoken_val);
      if ($("#autosave_pop").is(":hidden")) {
        $.post(
          ajax_auto_save_url,
          { mode: "list", csrfmiddlewaretoken: csrfmiddlewaretoken_val },
          function (data) {
            //alert(data);
            console.log("Data: " + data);
            $("#autosave_pop ul").empty();
            if (data.length) {
              $.each(data, function (i, item) {
                var id = item.id,
                  uid = item.uid,
                  subject = item.subject,
                  datetime = String(item.datetime);
                $("#autosave_pop ul")
                  .append('<li><a href="#none" class="autosave_load">' + subject + "</a><span>" + datetime + ' <button type="button" class="autosave_del">삭제</button></span></li>')
                  .find("li:eq(" + i + ")")
                  .data({ as_id: id, uid: uid });
              });
            }
          },
          "json"
        );
        $("#autosave_pop").show();
      } else {
        $("#autosave_pop").hide();
      }
    });

    // 임시저장된 글 제목과 내용을 가져와서 제목과 내용 입력박스에 노출해 줌
    $(document).on("click", ".autosave_load", function (e) {
      var $li = $(this).parents("li");
      var as_id = $li.data("as_id");
      var as_uid = $li.data("uid");
      $("#fwrite input[name='uid']").val(as_uid);
      $.post(
        ajax_auto_save_url,
        { as_id: as_id, mode: "load", csrfmiddlewaretoken: csrfmiddlewaretoken_val },
        function (data) {
          var subject = data.as_subject;
          var content = data.as_content;
          $("#wr_subject").val(subject);
          if (gnu_editor != "") {
            if (typeof put_editor_wr_content == "function") {
              put_editor_wr_content(content);
            }
          } else {
            $("#fwrite #wr_content").val(content);
          }
        },
        "json"
      );
      $("#autosave_pop").hide();
    });

    $(document).on("click", ".autosave_del", function (e) {
      var $li = $(this).parents("li");
      var as_id = $li.data("as_id");
      $.post(
        ajax_auto_save_url,
        { mode: "del", as_id: as_id, csrfmiddlewaretoken: csrfmiddlewaretoken_val },
        function (data) {
          if (data.count == -1) {
            alert("임시 저장된글을 삭제중에 오류가 발생하였습니다.");
          } else {
            $("#autosave_count").html(data.count);
            $li.remove();
          }
        },
        "json"
      );
    });

    $(".autosave_close").click(function (e) {
      $("#autosave_pop").hide();
    });
  });
} else {
  console.log("ajax_auto_save_url 변수가 없습니다. ");
}
